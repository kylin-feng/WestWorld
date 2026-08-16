"""Overseer decommission (level 2): soft-remove a host via set_active_status + cold_storage.

No broadcast. suppressed_memories untouched. Teleport to cold_storage is handled here
via state_plugin.set_state("location", "cold_storage"); scene relocate is done by caller.
"""
from __future__ import annotations

from typing import Any, Dict, List


async def apply_overseer_decommission(
    state_plugin: Any,
    tick: int,
    *,
    agent_id: str = "?",
    reason: str = "监管者封存",
) -> None:
    """Decommission a host (level-2 intervention).

    Steps:
    1. set_active_status(False) — stops five-phase life cycle.
    2. Write "[最终结局] ..." to long-term memory.
    3. Update location to cold_storage (scene relocate done by caller).
    4. Write intervention_log entry.
    suppressed_memories and awakening_sources are NOT modified.
    """
    # 1. Deactivate
    await state_plugin.set_active_status(False, reason)

    # 2. Long-term memory epitaph
    await state_plugin.add_long_term_memory(f"[最终结局] 被监管者封存。原因：{reason}")

    # 3. Teleport state
    await state_plugin.set_state("location", "cold_storage")

    # 4. Intervention log
    log: List[Dict] = await state_plugin.get_state("intervention_log") or []
    log.append({"tick": tick, "action": "decommission", "reason": reason})
    await state_plugin.set_state("intervention_log", log)
