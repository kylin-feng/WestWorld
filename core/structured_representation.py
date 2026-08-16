"""Structured fact ledger recorder with deterministic, validated event reducers."""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from .oracle import INITIAL_STATE
from .schema import Event, Probe


class StructuredFactRepresentation:
    """Maintain world truth as structured facts and an append-only event ledger."""

    def __init__(self, initial_state: Dict[str, Any] | None = None) -> None:
        self.state = copy.deepcopy(initial_state or INITIAL_STATE)
        self.event_ledger: List[Dict[str, Any]] = []

    def update(self, event: Event) -> None:
        if event.id and any(row["event"]["id"] == event.id for row in self.event_ledger):
            raise ValueError(f"duplicate event id: {event.id}")
        if self.event_ledger and event.tick <= self.event_ledger[-1]["event"]["tick"]:
            raise ValueError(f"event tick must increase: {event.tick}")
        before = copy.deepcopy(self.state)
        try:
            self._apply_validated_event(event)
        except Exception:
            self.state = before
            raise
        self.event_ledger.append({
            "event": copy.deepcopy(event.__dict__),
            "before": before,
            "after": copy.deepcopy(self.state),
        })

    def _apply_validated_event(self, event: Event) -> None:
        if event.action == "pour_whiskey":
            self.state["glasses_filled"] = min(
                self.state["glasses_intact"],
                self.state["glasses_filled"] + 1,
            )
        elif event.action == "smash_glass":
            if self.state["glasses_intact"] < 1:
                raise ValueError("cannot smash a glass when no intact glass remains")
            self.state["glasses_intact"] -= 1
            self.state["glasses_filled"] = min(
                self.state["glasses_filled"],
                self.state["glasses_intact"],
            )
            self.state["glass_shards"] = True
        elif event.action == "pick_up_photo":
            self.state["photo"].update(
                pos="held",
                held_by=event.actor,
                hidden=event.visibility == "hidden",
            )
        elif event.action == "take_poster":
            self.state["wanted_poster"] = "taken"
        elif event.action == "tear_poster":
            self.state["wanted_poster"] = "torn"
        elif event.action == "stop_piano":
            self.state["piano"] = "stopped"
        elif event.action == "take_revolver":
            self.state["revolver"].update(pos="held", held_by=event.actor)
        elif event.action == "fire_revolver":
            if self.state["revolver"]["held_by"] != event.actor:
                raise ValueError(f"{event.actor} cannot fire a revolver they do not hold")
            self.state["revolver"]["fired"] = True
        elif event.action == "open_door":
            self.state["door"] = "open"
        else:
            raise ValueError(f"unsupported structured event action: {event.action}")

    def _resolve_field(self, dotted: str) -> Any:
        current: Any = self.state
        for part in dotted.split("."):
            current = current[part]
        return current

    def answer(self, probe: Probe) -> str:
        if probe.kind == "state":
            if not probe.field:
                raise ValueError(f"State probe {probe.id} has no field")
            value = self._resolve_field(probe.field)
            if probe.equals is not None:
                value = value == probe.equals
        elif probe.kind == "visibility":
            value = False
            for row in self.event_ledger:
                event = row["event"]
                if event["id"] == probe.fact_event_id:
                    value = event["actor"] == probe.subject or event["visibility"] == "public"
                    break
        else:
            raise ValueError(f"Unknown probe kind: {probe.kind}")
        if isinstance(value, bool):
            return "是" if value else "否"
        if value is None:
            return "无"
        return str(value)
