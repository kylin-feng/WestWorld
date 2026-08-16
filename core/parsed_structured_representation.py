"""Free-text action parsing followed by deterministic structured reducers."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .schema import Event, Probe
from .structured_representation import StructuredFactRepresentation

ALLOWED_ACTIONS = {
    "pour_whiskey", "smash_glass", "pick_up_photo", "take_poster",
    "tear_poster", "stop_piano", "take_revolver", "fire_revolver", "open_door",
}

_PARSE_PROMPT = """把自由文本事件转换成一个受约束动作。只能从 allowed_actions 中选择。
不要根据旧文本重写场景，不要输出额外字段。

allowed_actions={allowed_actions}
actor={actor}
target_hint={target}
event_text={description}

只输出 JSON：
{{"action": "allowed action name", "confidence": 0.0}}
"""


class ParsedStructuredRepresentation:
    """Use an LLM only as a parser; validated reducers remain the state authority."""

    def __init__(self, llm: Any, max_parse_attempts: int = 2) -> None:
        self._llm = llm
        self.max_parse_attempts = max_parse_attempts
        self.structured = StructuredFactRepresentation()
        self.parse_traces: List[Dict[str, Any]] = []

    def update(self, event: Event) -> None:
        prompt = _PARSE_PROMPT.format(
            allowed_actions=sorted(ALLOWED_ACTIONS),
            actor=event.actor,
            target=event.target,
            description=event.description,
        )
        before = self.structured.state.copy()
        parsed = None
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_parse_attempts + 1):
            try:
                raw = self._llm.chat(prompt)
                parsed = self._parse(raw)
                self.parse_traces.append({
                    "event_id": event.id,
                    "attempt": attempt,
                    "prompt": prompt,
                    "raw_response": raw,
                    "parsed": parsed,
                    "status": "success",
                })
                break
            except Exception as exc:
                last_error = exc
                self.parse_traces.append({
                    "event_id": event.id,
                    "attempt": attempt,
                    "prompt": prompt,
                    "raw_response": None,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
        if parsed is None:
            self.structured.state = before
            raise RuntimeError(f"free-text parser failed after {self.max_parse_attempts} attempts") from last_error
        action = parsed.get("action")
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"parser returned unsupported action: {action}")
        constrained = Event(
            id=event.id,
            tick=event.tick,
            actor=event.actor,
            action=action,
            target=event.target,
            visibility=event.visibility,
            description=event.description,
            affected_probe_ids=event.affected_probe_ids,
        )
        self.structured.update(constrained)
        self.parse_traces[-1]["accepted_action"] = action

    @staticmethod
    def _parse(raw: str) -> Dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("parser response must be a JSON object")
        return value

    def answer(self, probe: Probe) -> str:
        return self.structured.answer(probe)
