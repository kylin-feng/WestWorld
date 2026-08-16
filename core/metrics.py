"""Answer normalization and comparison metrics."""
from __future__ import annotations

import re
from typing import Any, Dict, List

_TRUE_WORDS = ("true", "是的", "yes", "是", "有", "在")
_FALSE_WORDS = ("false", "不是", "不在", "没有", "否", "无", "no")


def normalize(answer: str, answer_type: str) -> str:
    text = (answer or "").strip().lower()
    if answer_type == "int":
        match = re.search(r"-?\d+", text)
        return match.group(0) if match else text.replace(" ", "")
    if answer_type == "bool":
        for word in _FALSE_WORDS:
            if word in text:
                return "false"
        for word in _TRUE_WORDS:
            if word in text:
                return "true"
    return text.replace(" ", "")


def is_correct(answer: str, truth: Any, answer_type: str, accepted_answers: tuple[str, ...] = ()) -> bool:
    if answer_type == "bool":
        truth_norm = "true" if truth else "false"
    elif truth is None:
        return normalize(answer, answer_type) in {"无", "none", "没人", "没有人"}
    else:
        truth_norm = str(truth).strip().lower()
    answer_norm = normalize(answer, answer_type)
    accepted = {normalize(candidate, answer_type) for candidate in accepted_answers}
    return answer_norm == truth_norm or answer_norm in accepted


def accuracy_over_ticks(records: List[Dict[str, Any]]) -> Dict[int, float]:
    grouped: Dict[int, List[bool]] = {}
    for record in records:
        grouped.setdefault(record["tick"], []).append(bool(record["correct"]))
    return {tick: sum(values) / len(values) for tick, values in grouped.items()}


def drift_slope(accuracy_by_tick: Dict[int, float]) -> float:
    ticks = sorted(accuracy_by_tick)
    if len(ticks) < 2:
        return 0.0
    mean_x = sum(ticks) / len(ticks)
    values = [accuracy_by_tick[tick] for tick in ticks]
    mean_y = sum(values) / len(values)
    denominator = sum((tick - mean_x) ** 2 for tick in ticks)
    return sum((tick - mean_x) * (value - mean_y) for tick, value in zip(ticks, values)) / denominator


def contradiction_count(records: List[Dict[str, Any]]) -> int:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["probe_id"], []).append(record)
    return sum(
        current["norm"] != previous["norm"] and current.get("evaluation_role") in {None, "persistence", "unaffected_baseline"}
        for sequence in grouped.values()
        for previous, current in zip(sorted(sequence, key=lambda item: item["tick"]), sorted(sequence, key=lambda item: item["tick"])[1:])
    )
