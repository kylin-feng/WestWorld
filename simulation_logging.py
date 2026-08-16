"""Structured, append-only logging for the West World simulation track."""
from __future__ import annotations

import copy
import json
import os
import platform
import shutil
import subprocess
import sys
import traceback
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import yaml


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _json_default(value: Any) -> str:
    return str(value)


def _redacted_models_config(path: Path) -> Any:
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and "api_key" in row:
                row["api_key"] = "REDACTED"
    return rows


_SENSITIVE_TRACE_FIELDS = {"prompt", "raw_response", "parsed_response", "pending_actions"}
_SENSITIVE_AGENT_STATE_FIELDS = {"feedback", "short_term_memory", "long_term_memory"}


def _trace_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a query-safe trace without prompts, model output, or hidden context."""
    return {
        key: value
        for key, value in row.items()
        if key not in _SENSITIVE_TRACE_FIELDS
    }


def _public_agent_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Strip private state and full model traces from query-facing logs."""
    public = copy.deepcopy(state)
    for key in _SENSITIVE_AGENT_STATE_FIELDS:
        public.pop(key, None)
    trace = public.get("plan_trace")
    if isinstance(trace, dict):
        public["plan_trace"] = _trace_summary(trace)
    percept = public.get("percept")
    if isinstance(percept, dict):
        percept.pop("messages", None)
    return public


def _usage_from_rows(rows: Iterable[Dict[str, Any]]) -> Counter:
    usage = Counter()
    for row in rows:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = row.get("usage", {}).get(key)
            if isinstance(value, int):
                usage[key] += value
    return usage


def check_state_consistency(
    agent_states: Dict[str, Dict[str, Any]],
    public_scenes: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Check the core invariant: each agent is present at exactly its state location."""
    memberships: Dict[str, list[str]] = {agent_id: [] for agent_id in agent_states}
    for location_id, snapshot in public_scenes.items():
        raw = snapshot.get("chunks", {}).get("present_agents", "")
        if raw and raw != "（无人）":
            for agent_id in str(raw).split("、"):
                if agent_id:
                    memberships.setdefault(agent_id, []).append(location_id)

    violations = []
    for agent_id, state in agent_states.items():
        expected = state.get("location")
        actual = sorted(memberships.get(agent_id, []))
        if actual != [expected]:
            violations.append({
                "agent_id": agent_id,
                "expected_location": expected,
                "recorder_locations": actual,
            })
    return {
        "ok": not violations,
        "agent_count": len(agent_states),
        "violations": violations,
    }


class SimulationLogArchive:
    """Write a complete simulation run into one timestamped directory."""

    def __init__(
        self,
        project_path: str | Path,
        max_ticks: int,
        agent_ids: Iterable[str],
        active_location_ids: Iterable[str],
        run_dir: Optional[str | Path] = None,
    ) -> None:
        self.project_path = Path(project_path)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        configured_dir = run_dir or os.environ.get("WW_RUN_DIR")
        output_root = Path(os.environ.get("WW_OUTPUT_DIR", self.project_path / "output" / "sim_runs"))
        self.run_dir = Path(configured_dir) if configured_dir else output_root / run_id
        if self.run_dir.exists() and any(self.run_dir.iterdir()):
            raise ValueError(f"simulation run directory is not empty: {self.run_dir}")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.run_dir / "manifest.json"
        self.sequence = 0
        self.manifest: Dict[str, Any] = {
            "run_id": self.run_dir.name,
            "protocol_version": "west-world-sim-log-v1",
            "status": "running",
            "started_at": _now(),
            "max_ticks": max_ticks,
            "agent_ids": list(agent_ids),
            "active_location_ids": list(active_location_ids),
            "completed_ticks": 0,
            "record_counts": {
                "events": 0,
                "timeline_snapshots": 0,
                "agent_state_rows": 0,
                "public_scene_rows": 0,
                "internal_scene_rows": 0,
                "model_trace_rows": 0,
                "model_attempt_rows": 0,
                "consistency_violations": 0,
                "scene_errors": 0,
                "world_object_snapshots": 0,
            },
            "files": {
                "timeline": "timeline.jsonl",
                "events": "events.jsonl",
                "agent_states": "agent_states.jsonl",
                "agent_states_internal": "internal/agent_states.jsonl",
                "scene_snapshots_public": "scene_snapshots_public.jsonl",
                "scene_snapshots_internal": "scene_snapshots_internal.jsonl",
                "model_traces": "model_traces.jsonl",
                "model_traces_internal": "internal/model_traces.jsonl",
                "llm_requests": "raw/llm_requests.jsonl",
                "llm_attempts": "raw/llm_attempts.jsonl",
                "world_objects_snapshots": "world_objects_snapshots.jsonl",
            },
        }
        self._write_provenance()
        self._archive_inputs()
        self._write_readme()
        self._write_manifest()
        self.record_event("run_started", max_ticks=max_ticks)

    def _write_json(self, relative_path: str, value: Any) -> None:
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _append_jsonl(self, relative_path: str, value: Dict[str, Any]) -> None:
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(value, ensure_ascii=False, default=_json_default) + "\n")
            file.flush()

    def _write_manifest(self) -> None:
        self._write_json("manifest.json", self.manifest)

    def _write_provenance(self) -> None:
        try:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=self.project_path, text=True
            ).strip()
        except Exception:
            git_commit = "unknown"
        self._write_json("provenance.json", {
            "git_commit": git_commit,
            "python": sys.version,
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
            "project_path": str(self.project_path),
        })

    def _archive_inputs(self) -> None:
        inputs = self.run_dir / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        for name in ("configs", "data"):
            source = self.project_path / name
            if source.exists():
                if name == "configs":
                    shutil.copytree(source, inputs / name, ignore=shutil.ignore_patterns("models_config.yaml"))
                else:
                    shutil.copytree(source, inputs / name)
        models = self.project_path / "configs" / "models_config.yaml"
        if models.exists():
            redacted = _redacted_models_config(models)
            (inputs / "configs" / "models_config.redacted.yaml").write_text(
                yaml.safe_dump(redacted, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

    def _write_readme(self) -> None:
        (self.run_dir / "README.md").write_text(
            """# West World Simulation Run

- `timeline.jsonl`: initial and tick-end aggregate snapshots.
- `agent_states.jsonl`: query-safe state rows without private feedback, messages, memory, or full plan traces.
- `internal/agent_states.jsonl`: full state rows for private diagnostics.
- `scene_snapshots_public.jsonl`: replay-safe scene state without hidden notes.
- `scene_snapshots_internal.jsonl`: private diagnostics with hidden notes and pending actions.
- `world_objects_snapshots.jsonl`: world-level object registry snapshots (objects + ledger) per tick.
- `model_traces.jsonl`: query-safe request summaries without prompts or model output.
- `internal/model_traces.jsonl`: full prompts, model output, parsed output, and available usage.
- `events.jsonl`: ordered lifecycle and phase events.
- `raw/llm_attempts.jsonl`: one row per provider attempt, including failures, retries, latency, and exact usage.
- `views/`: query-oriented tick, agent, location, slow-request, and failure views.
- `summary.json` and `report/report.md`: aggregate run diagnostics.
- `inputs/`: archived inputs; model credentials are redacted.

Do not expose `scene_snapshots_internal.jsonl` or `internal/` to agents or a public frontend.
""",
            encoding="utf-8",
        )

    def record_event(self, event_type: str, **details: Any) -> None:
        self.sequence += 1
        row = {
            "schema_version": "1.0",
            "run_id": self.manifest["run_id"],
            "event_id": f"evt_{uuid.uuid4().hex}",
            "sequence": self.sequence,
            "timestamp": _now(),
            "event_type": event_type,
            **details,
        }
        self._append_jsonl("events.jsonl", row)
        self._append_jsonl("raw/events.jsonl", row)
        self.manifest["record_counts"]["events"] += 1
        self._write_manifest()

    def record_tick(
        self,
        tick: int,
        agent_states: Dict[str, Dict[str, Any]],
        public_scenes: Dict[str, Dict[str, Any]],
        internal_scenes: Dict[str, Dict[str, Any]],
        phase_timings_seconds: Dict[str, float],
        scene_errors: list[Dict[str, Any]],
        phase: str = "tick_end",
        count_completed_tick: bool = True,
    ) -> Dict[str, Any]:
        consistency = check_state_consistency(agent_states, public_scenes)
        public_agent_states = {
            agent_id: _public_agent_state(state)
            for agent_id, state in agent_states.items()
        }
        row = {
            "tick": tick,
            "phase": phase,
            "timestamp": _now(),
            "phase_timings_seconds": phase_timings_seconds,
            "scene_errors": scene_errors,
            "consistency": consistency,
            "agents": public_agent_states,
            "scenes": public_scenes,
        }
        self._append_jsonl("timeline.jsonl", row)
        counts = self.manifest["record_counts"]
        counts["timeline_snapshots"] += 1
        counts["consistency_violations"] += len(consistency["violations"])
        counts["scene_errors"] += len(scene_errors)

        for agent_id, state in agent_states.items():
            self._append_jsonl("agent_states.jsonl", {
                "tick": tick, "phase": phase, "timestamp": row["timestamp"],
                "agent_id": agent_id, "state": public_agent_states[agent_id],
            })
            self._append_jsonl("internal/agent_states.jsonl", {
                "tick": tick, "phase": phase, "timestamp": row["timestamp"],
                "agent_id": agent_id, "state": state,
            })
            counts["agent_state_rows"] += 1
            trace = state.get("plan_trace")
            if trace:
                request_row = {
                    "schema_version": "1.0",
                    "run_id": self.manifest["run_id"],
                    "tick": tick, "phase": phase, "timestamp": row["timestamp"], "source": "agent_plan",
                    "agent_id": agent_id, **trace,
                }
                self._append_jsonl("internal/model_traces.jsonl", request_row)
                self._append_jsonl("model_traces.jsonl", _trace_summary(request_row))
                self._append_jsonl("raw/llm_requests.jsonl", _trace_summary(request_row))
                counts["model_trace_rows"] += 1

        for location_id, snapshot in public_scenes.items():
            self._append_jsonl("scene_snapshots_public.jsonl", {
                "tick": tick, "phase": phase, "timestamp": row["timestamp"],
                "location_id": location_id, **snapshot,
            })
            counts["public_scene_rows"] += 1
        for location_id, snapshot in internal_scenes.items():
            traces = snapshot.get("llm_traces", [])
            snapshot_without_traces = {key: value for key, value in snapshot.items() if key != "llm_traces"}
            self._append_jsonl("scene_snapshots_internal.jsonl", {
                "tick": tick, "phase": phase, "timestamp": row["timestamp"],
                "location_id": location_id, **snapshot_without_traces,
            })
            counts["internal_scene_rows"] += 1
            for trace in traces:
                request_row = {
                    "schema_version": "1.0",
                    "run_id": self.manifest["run_id"],
                    "tick": tick, "phase": phase, "timestamp": row["timestamp"],
                    "source": "location_recorder",
                    "location_id": location_id, **trace,
                }
                self._append_jsonl("internal/model_traces.jsonl", request_row)
                self._append_jsonl("model_traces.jsonl", _trace_summary(request_row))
                self._append_jsonl("raw/llm_requests.jsonl", _trace_summary(request_row))
                counts["model_trace_rows"] += 1

        if count_completed_tick:
            self.manifest["completed_ticks"] += 1
        self.manifest["last_tick"] = tick
        self.manifest["last_consistency_ok"] = consistency["ok"]
        self._write_manifest()
        return consistency

    def record_model_attempts(self, tick: int, attempts: list[Dict[str, Any]]) -> None:
        for attempt in attempts:
            self._append_jsonl("raw/llm_attempts.jsonl", {
                "schema_version": "1.0",
                "run_id": self.manifest["run_id"],
                "tick_collected": tick,
                **attempt,
            })
        self.manifest["record_counts"]["model_attempt_rows"] += len(attempts)
        self._write_manifest()

    def record_world_objects(self, tick: int, snapshot: Dict[str, Any]) -> None:
        self._append_jsonl("world_objects_snapshots.jsonl", {"tick": tick, **snapshot})
        self.manifest["record_counts"]["world_object_snapshots"] += 1
        self._write_manifest()

    def _read_jsonl(self, relative_path: str) -> list[Dict[str, Any]]:
        path = self.run_dir / relative_path
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write_views_and_summary(self) -> None:
        timeline = self._read_jsonl("timeline.jsonl")
        requests = self._read_jsonl("raw/llm_requests.jsonl")
        attempts = self._read_jsonl("raw/llm_attempts.jsonl")
        events = self._read_jsonl("events.jsonl")
        views = self.run_dir / "views"
        if views.exists():
            shutil.rmtree(views)

        actions = Counter()
        for snapshot in timeline:
            tick = snapshot.get("tick", -1)
            self._write_json(f"views/ticks/tick_{tick:04d}.json", snapshot)
            for agent_id, state in snapshot.get("agents", {}).items():
                self._append_jsonl(f"views/agents/{agent_id}.jsonl", {
                    "tick": tick, "phase": snapshot.get("phase"), "state": state,
                })
                action = state.get("plan_decision", {}).get("action")
                if tick >= 0 and action:
                    actions[action] += 1
            for location_id, scene in snapshot.get("scenes", {}).items():
                self._append_jsonl(f"views/locations/{location_id}.jsonl", {
                    "tick": tick, "phase": snapshot.get("phase"), "scene": scene,
                })

        recorder_attempts = [row for row in requests if row.get("source") == "location_recorder"]
        combined_attempts = attempts + recorder_attempts
        failed_attempts = [row for row in combined_attempts if row.get("status") == "failed"]
        attempts_by_request: Dict[str, list[Dict[str, Any]]] = {}
        for index, row in enumerate(combined_attempts):
            request_id = str(row.get("request_id") or f"unidentified-{index}")
            attempts_by_request.setdefault(request_id, []).append(row)

        def request_succeeded(rows: list[Dict[str, Any]]) -> bool:
            return any(
                row.get("status") == "success"
                or (
                    row.get("source") == "agent_plan"
                    and not row.get("error")
                    and row.get("parse_fallback") is not True
                )
                for row in rows
            )

        failed_request_groups = {
            request_id: rows
            for request_id, rows in attempts_by_request.items()
            if not request_succeeded(rows)
        }
        failed_requests = [rows[-1] for rows in failed_request_groups.values()]
        slow_attempts = sorted(
            combined_attempts,
            key=lambda row: row.get("duration_ms", 0),
            reverse=True,
        )
        for row in slow_attempts:
            self._append_jsonl("views/slow_requests.jsonl", _trace_summary(row))
        for row in failed_attempts:
            self._append_jsonl("views/failures.jsonl", {"record_type": "provider_attempt", **row})
        for row in failed_requests:
            self._append_jsonl("views/failures.jsonl", {"record_type": "business_request", **row})

        usage = _usage_from_rows(combined_attempts)
        latencies = sorted(row.get("duration_ms", 0) for row in combined_attempts)
        percentile = lambda p: latencies[min(int((len(latencies) - 1) * p), len(latencies) - 1)] if latencies else None
        summary = {
            "run_id": self.manifest["run_id"],
            "status": self.manifest["status"],
            "ticks": self.manifest["completed_ticks"],
            "agents": len(self.manifest["agent_ids"]),
            "locations": len(self.manifest["active_location_ids"]),
            "actions": dict(actions),
            "llm": {
                "logical_requests": len({
                    row.get("request_id") or f"unidentified-{index}"
                    for index, row in enumerate(requests)
                }),
                "attempts": len(combined_attempts),
                "failed_attempts": len(failed_attempts),
                "failed_requests": len(failed_request_groups),
                "retries": max(
                    0,
                    len(combined_attempts) - len({
                        row["request_id"] for row in combined_attempts if row.get("request_id")
                    }),
                ),
                "usage": dict(usage),
                "p50_latency_ms": percentile(0.50),
                "p95_latency_ms": percentile(0.95),
                "max_latency_ms": max(latencies) if latencies else None,
            },
            "consistency_violations": self.manifest["record_counts"]["consistency_violations"],
            "scene_errors": self.manifest["record_counts"]["scene_errors"],
            "slowest_requests": [_trace_summary(row) for row in slow_attempts[:10]],
            "failed_events": [row for row in events if "failed" in row.get("event_type", "")],
        }
        self._write_json("summary.json", summary)
        lines = [
            f"# West World Run {summary['run_id']}", "",
            f"- Status: `{summary['status']}`",
            f"- Completed ticks: {summary['ticks']}",
            f"- LLM logical requests: {summary['llm']['logical_requests']}",
            f"- LLM attempts: {summary['llm']['attempts']}",
            f"- Failed attempts: {summary['llm']['failed_attempts']}",
            f"- Total tokens: {summary['llm']['usage'].get('total_tokens', 0)}",
            f"- Consistency violations: {summary['consistency_violations']}",
            "", "## Slowest Attempts", "",
            "| Request | Attempt | Agent | Model | Status | Duration ms |",
            "|---|---|---|---|---|---:|",
        ]
        for row in slow_attempts[:10]:
            agent_value = row.get("agent_id") or ", ".join(row.get("agent_ids") or [])
            lines.append(
                f"| `{row.get('request_id', '')}` | `{row.get('attempt_id', '')}` | "
                f"{agent_value} | "
                f"{row.get('model', '')} | {row.get('status', '')} | {row.get('duration_ms', 0)} |"
            )
        (self.run_dir / "report").mkdir(exist_ok=True)
        (self.run_dir / "report" / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def complete(self) -> None:
        self.manifest.update(status="completed", completed_at=_now())
        self.record_event("run_completed", completed_ticks=self.manifest["completed_ticks"])
        self._write_views_and_summary()
        self._write_manifest()

    def fail(self, exc: BaseException) -> None:
        self.manifest.update(
            status="failed",
            failed_at=_now(),
            error=f"{type(exc).__name__}: {exc}",
            traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
        self.record_event("run_failed", error=self.manifest["error"])
        self._write_views_and_summary()
        self._write_manifest()
