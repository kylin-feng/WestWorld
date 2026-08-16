"""Query West World simulation run archives."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable

PROJECT = Path(__file__).resolve().parent
DEFAULT_ROOT = PROJECT / "output" / "sim_runs"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def list_runs(root: Path) -> list[Dict[str, Any]]:
    rows = []
    if not root.exists():
        return rows
    for run_dir in sorted((path for path in root.iterdir() if path.is_dir()), reverse=True):
        manifest = run_dir / "manifest.json"
        if manifest.exists():
            row = _load_json(manifest)
            rows.append({
                "run_id": run_dir.name,
                "status": row.get("status"),
                "started_at": row.get("started_at"),
                "completed_ticks": row.get("completed_ticks"),
                "path": str(run_dir),
            })
    return rows


def resolve_run(root: Path, run_id: str) -> Path:
    direct = Path(run_id)
    run_dir = direct if direct.is_dir() else root / run_id
    if not run_dir.is_dir():
        raise SystemExit(f"run not found: {run_id}")
    return run_dir


def query_tick(run_dir: Path, tick: int) -> Dict[str, Any]:
    path = run_dir / "views" / "ticks" / f"tick_{tick:04d}.json"
    if path.exists():
        return _load_json(path)
    rows = [row for row in _load_jsonl(run_dir / "timeline.jsonl") if row.get("tick") == tick]
    if not rows:
        raise SystemExit(f"tick not found: {tick}")
    return rows[-1]


def _filter_rows(rows: Iterable[Dict[str, Any]], key: str, value: str) -> list[Dict[str, Any]]:
    return [row for row in rows if row.get(key) == value]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("runs")
    for name in ("summary", "failures"):
        cmd = sub.add_parser(name)
        cmd.add_argument("run_id")
    tick = sub.add_parser("tick")
    tick.add_argument("run_id")
    tick.add_argument("tick", type=int)
    agent = sub.add_parser("agent")
    agent.add_argument("run_id")
    agent.add_argument("agent_id")
    location = sub.add_parser("location")
    location.add_argument("run_id")
    location.add_argument("location_id")
    slow = sub.add_parser("slow")
    slow.add_argument("run_id")
    slow.add_argument("--threshold-ms", type=float, default=10000)

    args = parser.parse_args()
    if args.command == "runs":
        _print(list_runs(args.root))
        return
    run_dir = resolve_run(args.root, args.run_id)
    if args.command == "summary":
        path = run_dir / "summary.json"
        _print(_load_json(path) if path.exists() else _load_json(run_dir / "manifest.json"))
    elif args.command == "tick":
        _print(query_tick(run_dir, args.tick))
    elif args.command == "agent":
        path = run_dir / "views" / "agents" / f"{args.agent_id}.jsonl"
        rows = _load_jsonl(path) or _filter_rows(_load_jsonl(run_dir / "agent_states.jsonl"), "agent_id", args.agent_id)
        _print(rows)
    elif args.command == "location":
        path = run_dir / "views" / "locations" / f"{args.location_id}.jsonl"
        rows = _load_jsonl(path) or _filter_rows(
            _load_jsonl(run_dir / "scene_snapshots_public.jsonl"), "location_id", args.location_id
        )
        _print(rows)
    elif args.command == "slow":
        rows = _load_jsonl(run_dir / "raw" / "llm_attempts.jsonl")
        _print(sorted(
            (row for row in rows if row.get("duration_ms", 0) >= args.threshold_ms),
            key=lambda row: row.get("duration_ms", 0),
            reverse=True,
        ))
    elif args.command == "failures":
        attempts = [
            row for row in _load_jsonl(run_dir / "raw" / "llm_attempts.jsonl")
            if row.get("status") == "failed"
        ]
        events = [
            row for row in _load_jsonl(run_dir / "events.jsonl")
            if "failed" in row.get("event_type", "")
        ]
        _print({"llm_attempts": attempts, "events": events})


if __name__ == "__main__":
    main()
