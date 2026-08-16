"""M2 占位决策：随机停留或移动到激活邻接地点，不调 LLM。"""
from __future__ import annotations

import random
from typing import Any, Dict, Optional

from agentkernel_distributed.mas.agent.base.plugin_base import PlanPlugin


def decide(percept: Dict[str, Any], seed: Optional[int] = None) -> Dict[str, Any]:
    rng = random.Random(seed)
    neighbors = percept.get("neighbors", [])
    if neighbors and rng.random() < 0.5:
        return {"action": "move", "target": rng.choice(neighbors)}
    return {"action": "stay", "target": ""}


class RandomWalkPlanPlugin(PlanPlugin):
    """M2 随机游走决策插件：从 state 读 percept，写入 plan 决策。"""

    def __init__(self, **_: Any) -> None:
        super().__init__()

    async def init(self) -> None:
        pass

    async def execute(self, current_tick: int) -> None:
        if self.agent is None:
            return
        state_component = self.agent.get_component("state")
        state_plugin = state_component.get_plugin()

        percept = await state_plugin.get_state("percept") or {}
        decision = decide(percept)
        await state_plugin.set_state("plan_decision", decision)

    async def save_to_db(self) -> None:
        return None

    async def load_from_db(self) -> None:
        return None
