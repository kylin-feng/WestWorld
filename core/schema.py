"""Core data models and JSONL loaders for the recorder comparison."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

SCORE_GROUPS = {"visual_snapshot", "temporal_nonvisual", "hidden_knowledge"}


@dataclass
class Event:
    tick: int
    actor: str
    action: str
    target: str
    visibility: str = "public"
    id: Optional[str] = None
    description: str = ""
    affected_probe_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        return cls(
            tick=int(data["tick"]),
            actor=data["actor"],
            action=data["action"],
            target=data["target"],
            visibility=data.get("visibility", "public"),
            id=data.get("id"),
            description=data.get("description", ""),
            affected_probe_ids=tuple(data.get("affected_probe_ids", ())),
        )


@dataclass
class Probe:
    id: str
    kind: str
    text: str
    answer_type: str
    field: Optional[str] = None
    equals: Optional[Any] = None
    subject: Optional[str] = None
    fact_event_id: Optional[str] = None
    score_group: str = "visual_snapshot"
    accepted_answers: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Probe":
        return cls(
            id=data["id"],
            kind=data["kind"],
            text=data["text"],
            answer_type=data.get("answer_type", "str"),
            field=data.get("field"),
            equals=data.get("equals"),
            subject=data.get("subject"),
            fact_event_id=data.get("fact_event_id"),
            score_group=data.get("score_group", "visual_snapshot"),
            accepted_answers=tuple(data.get("accepted_answers", ())),
        )


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_events(path: str) -> List[Event]:
    return [Event.from_dict(row) for row in _load_jsonl(path)]


def load_probes(path: str) -> List[Probe]:
    return [Probe.from_dict(row) for row in _load_jsonl(path)]


def validate_protocol(events: List[Event], probes: List[Probe]) -> None:
    event_ids = [event.id for event in events]
    probe_ids = [probe.id for probe in probes]
    if any(event_id is None for event_id in event_ids) or len(event_ids) != len(set(event_ids)):
        raise ValueError("Every event must have a unique non-empty id")
    if len(probe_ids) != len(set(probe_ids)):
        raise ValueError("Every probe must have a unique id")
    if len({event.tick for event in events}) != len(events):
        raise ValueError("Every event must have a unique tick")
    probe_id_set = set(probe_ids)
    for event in events:
        if not event.description.strip():
            raise ValueError(f"Event {event.id} has no explicit description")
        if not event.affected_probe_ids:
            raise ValueError(f"Event {event.id} has no affected probes")
        unknown = set(event.affected_probe_ids) - probe_id_set
        if unknown:
            raise ValueError(f"Event {event.id} references unknown probes: {sorted(unknown)}")
    for probe in probes:
        if probe.score_group not in SCORE_GROUPS:
            raise ValueError(f"Probe {probe.id} has unknown score group: {probe.score_group}")
