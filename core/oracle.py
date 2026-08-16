"""Deterministic ground-truth state machine for the recorder comparison."""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from .schema import Event, Probe

INITIAL_STATE: Dict[str, Any] = {
    "glasses_intact": 3,
    "glasses_filled": 0,
    "glass_shards": False,
    "wanted_poster": "on_wall",
    "photo": {"pos": "floor", "held_by": None, "hidden": False},
    "piano": "playing",
    "revolver": {"pos": "table", "held_by": None, "fired": False},
    "door": "closed",
}


class OracleState:
    def __init__(self) -> None:
        self.state = copy.deepcopy(INITIAL_STATE)
        self.event_log: List[Event] = []

    def apply(self, event: Event) -> None:
        self.event_log.append(event)
        if event.action == "pour_whiskey":
            self.state["glasses_filled"] = min(self.state["glasses_intact"], self.state["glasses_filled"] + 1)
        elif event.action == "smash_glass":
            self.state["glasses_intact"] = max(0, self.state["glasses_intact"] - 1)
            self.state["glasses_filled"] = min(self.state["glasses_filled"], self.state["glasses_intact"])
            self.state["glass_shards"] = True
        elif event.action == "pick_up_photo":
            self.state["photo"].update(pos="held", held_by=event.actor, hidden=event.visibility == "hidden")
        elif event.action == "take_poster":
            self.state["wanted_poster"] = "taken"
        elif event.action == "tear_poster":
            self.state["wanted_poster"] = "torn"
        elif event.action == "stop_piano":
            self.state["piano"] = "stopped"
        elif event.action == "take_revolver":
            self.state["revolver"].update(pos="held", held_by=event.actor)
        elif event.action == "fire_revolver":
            self.state["revolver"]["fired"] = True
        elif event.action == "open_door":
            self.state["door"] = "open"

    def _resolve_field(self, dotted: str) -> Any:
        current: Any = self.state
        for part in dotted.split("."):
            current = current[part]
        return current

    def answer(self, probe: Probe) -> Any:
        if probe.kind == "state":
            if not probe.field:
                raise ValueError(f"State probe {probe.id} has no field")
            value = self._resolve_field(probe.field)
            return value == probe.equals if probe.equals is not None else value
        if probe.kind == "visibility":
            for event in self.event_log:
                if event.id == probe.fact_event_id:
                    return event.actor == probe.subject or event.visibility == "public"
            return False
        raise ValueError(f"Unknown probe kind: {probe.kind}")
