"""Run fixed events against recorder representations and score their answers."""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Callable, Dict, List, Optional

from .metrics import accuracy_over_ticks, contradiction_count, drift_slope, is_correct, normalize
from .oracle import OracleState
from .schema import Event, Probe, load_events, load_probes, validate_protocol

def _is_relevant(probe: Probe, event: Event) -> bool:
    return probe.id in event.affected_probe_ids


def _accuracy(records: List[Dict[str, Any]]) -> Optional[float]:
    return sum(record["correct"] for record in records) / len(records) if records else None


def _record_answers(
    tick: int,
    probes: List[Probe],
    representations: Dict[str, Any],
    oracle: OracleState,
    evaluation_roles: Dict[str, str],
    records: List[Dict[str, Any]],
    on_record: Optional[Callable[[Dict[str, Any]], None]],
) -> None:
    for probe in probes:
        truth = oracle.answer(probe)
        for name, representation in representations.items():
            raw = representation.answer(probe)
            record = {
                "tick": tick, "method": name, "probe_id": probe.id, "answer": raw,
                "norm": normalize(raw, probe.answer_type), "truth": truth,
                "correct": is_correct(raw, truth, probe.answer_type, probe.accepted_answers),
                "evaluation_role": evaluation_roles[probe.id],
                "had_relevant_event": evaluation_roles[probe.id] == "affected",
                "score_group": probe.score_group,
            }
            records.append(record)
            if on_record:
                on_record(record)


def run_comparison(
    events: List[Event],
    probes: List[Probe],
    rep_factories: Dict[str, Callable[[], Any]],
    on_record: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    oracle = OracleState()
    representations = {name: factory() for name, factory in rep_factories.items()}
    records: List[Dict[str, Any]] = []
    _record_answers(
        0, probes, representations, oracle,
        {probe.id: "initial" for probe in probes}, records, on_record,
    )
    affected_seen: set[str] = set()
    for event in sorted(events, key=lambda item: item.tick):
        oracle.apply(event)
        for representation in representations.values():
            representation.update(event)
        roles = {}
        for probe in probes:
            if _is_relevant(probe, event):
                roles[probe.id] = "affected"
                affected_seen.add(probe.id)
            elif probe.id in affected_seen:
                roles[probe.id] = "persistence"
            else:
                roles[probe.id] = "unaffected_baseline"
        _record_answers(event.tick, probes, representations, oracle, roles, records, on_record)
    summary = {}
    for name in representations:
        method_records = [record for record in records if record["method"] == name]
        final_tick = max(record["tick"] for record in method_records)
        by_tick = accuracy_over_ticks(method_records)
        summary[name] = {
            "accuracy": _accuracy(method_records),
            "initial_accuracy": _accuracy([r for r in method_records if r["evaluation_role"] == "initial"]),
            "affected_accuracy": _accuracy([r for r in method_records if r["evaluation_role"] == "affected"]),
            "persistence_accuracy": _accuracy([r for r in method_records if r["evaluation_role"] == "persistence"]),
            "final_state_accuracy": _accuracy([r for r in method_records if r["tick"] == final_tick]),
            "accuracy_by_tick": by_tick,
            "drift_slope": drift_slope(by_tick),
            "contradictions": contradiction_count(method_records),
            "accuracy_by_group": {
                group: _accuracy([r for r in method_records if r["score_group"] == group])
                for group in sorted({r["score_group"] for r in method_records})
            },
            "accuracy_by_group_role": {
                group: {
                    role: _accuracy([
                        r for r in method_records
                        if r["score_group"] == group and r["evaluation_role"] == role
                    ])
                    for role in ("initial", "affected", "persistence", "unaffected_baseline")
                }
                for group in sorted({r["score_group"] for r in method_records})
            },
        }
    return {"records": records, "summary": summary}


def _build_real_reps(method: str, config_path: str) -> Dict[str, Callable[[], Any]]:
    from ..adapters.model_clients import build_image_gen, build_llm, build_vlm
    from .image_representation import ImageRepresentation
    from .structured_representation import StructuredFactRepresentation
    from .text_representation import TextRepresentation

    factories: Dict[str, Callable[[], Any]] = {}
    if method in ("text", "both", "all"):
        factories["text"] = lambda: TextRepresentation(build_llm(config_path))
    if method in ("image", "both", "all"):
        factories["image"] = lambda: ImageRepresentation(build_image_gen(config_path), build_vlm(config_path))
    if method in ("structured", "all"):
        factories["structured"] = StructuredFactRepresentation
    return factories


def main() -> None:
    parser = argparse.ArgumentParser()
    project = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    parser.add_argument(
        "--method",
        choices=["text", "image", "structured", "both", "all"],
        default="both",
    )
    parser.add_argument("--data-dir", default=os.path.join(project, "data"))
    parser.add_argument("--config", default=os.path.join(project, "configs", "models_config.yaml"))
    parser.add_argument("--out", default=os.path.join(project, "results.jsonl"))
    args = parser.parse_args()
    events = load_events(os.path.join(args.data_dir, "script.jsonl"))
    probes = load_probes(os.path.join(args.data_dir, "probes.jsonl"))
    validate_protocol(events, probes)
    result = run_comparison(events, probes, _build_real_reps(args.method, args.config))
    with open(args.out, "w", encoding="utf-8") as file:
        for record in result["records"]:
            file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
