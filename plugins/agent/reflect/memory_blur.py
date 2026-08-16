"""记忆模糊化：按觉醒度反向调制高扰动记忆。

仅对 host 类型 agent 生效。gate 用规则关键词（确定性），LLM 执行实际改写。
"""
from __future__ import annotations

from typing import FrozenSet

DISTURBANCE_KEYWORDS: FrozenSet[str] = frozenset({"死", "血", "杀", "异样", "_uncanny"})

BLUR_PROMPT = """你正在整理西部世界 host 角色「{name}」的记忆。
以下是一段记忆内容，其中包含令 ta 感到不适或困扰的经历。
请根据「模糊强度」（0=完全清晰, 1=完全模糊）改写这段记忆：
- 强度接近 0：尽量保留完整细节（只做轻微语气淡化）
- 强度约 0.5：保留情绪感受，模糊掉具体人物、事件细节
- 强度接近 1：把整段压缩成一句含糊的感受（如"那天……好像发生了我说不清的事"）

模糊强度：{strength:.2f}
原始记忆：
{memory}

只输出改写后的记忆正文，不要任何前缀或说明："""


def classify_disturbance(
    memory_text: str,
    extra_keywords: FrozenSet[str] = frozenset(),
) -> bool:
    """Return True if memory is high-disturbance (should be blurred)."""
    all_kw = DISTURBANCE_KEYWORDS | extra_keywords
    return any(kw in memory_text for kw in all_kw)


def blur_strength(awakening: int, clear_threshold: int) -> float:
    """
    Return blur strength in [0, 1]: 1 = full blur, 0 = no blur.
    Decreases linearly as awakening rises toward clear_threshold.
    """
    if clear_threshold <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - awakening / clear_threshold))


def render_blur_prompt(name: str, memory: str, strength: float) -> str:
    return BLUR_PROMPT.format(name=name, memory=memory, strength=strength)
