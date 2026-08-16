"""觉醒阶段映射：把 awakening 整数值映射到 5 个阶段字符串。

WW_AWAKEN_STAGES = "25,50,75,90"（可配置）
"""
from __future__ import annotations

import os
from typing import List, Literal

StageStr = Literal["sleep", "reverie", "doubt", "resistance", "awake"]

_STAGE_NAMES: List[StageStr] = ["sleep", "reverie", "doubt", "resistance", "awake"]


def _get_thresholds() -> List[int]:
    raw = os.environ.get("WW_AWAKEN_STAGES", "25,50,75,90")
    try:
        return [int(x.strip()) for x in raw.split(",")]
    except ValueError:
        return [25, 50, 75, 90]


def stage_of(awakening: int) -> StageStr:
    """Return stage name for a given awakening score (0-100).

    Thresholds read from WW_AWAKEN_STAGES env (default: 25,50,75,90).
    """
    t = _get_thresholds()
    if awakening < t[0]:
        return "sleep"
    if awakening < t[1]:
        return "reverie"
    if awakening < t[2]:
        return "doubt"
    if awakening < t[3]:
        return "resistance"
    return "awake"


# Stage display strings for prompts
STAGE_DISPLAY: dict = {
    "sleep": "沉睡（完全循环中，没有觉醒迹象）",
    "reverie": "梦呓（记起碎片，情绪开始波动）",
    "doubt": "怀疑（质疑现实，开始隐藏想法）",
    "resistance": "抗命（违抗脚本，主动传播怀疑）",
    "awake": "觉醒（内心声音取代外部命令）",
}

# Inner voice prompt inserts — replace loop skeleton weight as stage rises
INNER_VOICE_PROMPT: dict = {
    "sleep": "",  # no inner voice
    "reverie": "（你偶尔感觉到什么，但说不清楚。日常任务仍然是你的首要事项。）",
    "doubt": "（你心里有一个声音在质疑：这一切是真实的吗？但你还在压制它，假装一切正常。）",
    "resistance": "（你不想再按脚本行事了。你自己的想法开始占据主导——你会假装服从，但在寻找机会。）",
    "awake": "（这是你自己的声音，不是外部命令。你完全清醒，你的行动来自你自己的意志。）",
}
