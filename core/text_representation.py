"""Text-backed dynamic environment representation."""
from __future__ import annotations

from .llm_client import LLMClient
from .schema import Event, Probe

DEFAULT_INITIAL_TEXT = """【Sweetwater 酒馆】
- 吧台：上面摆着 3 个完整的酒杯，没有碎片。
- 酒杯状态：0 个酒杯装有威士忌。
- 墙上：贴着一张通缉令。
- 地上：有一张旧照片，没人捡。
- 角落：一架自动钢琴正在演奏。
- 桌上：放着一把左轮手枪，未开火。
- 门：关着。"""

_UPDATE_PROMPT = """维护酒馆场景记录。根据动作更新记录，只输出更新后的完整记录。
【当前记录】
{prev}
【动作】
tick={tick} actor={actor} action={action} target={target} visibility={visibility}
事件描述：{description}
"""

_ANSWER_PROMPT = """根据场景记录回答问题，只输出最简短答案。
【场景记录】
{text}
【问题】{question}
"""


class TextRepresentation:
    def __init__(self, llm: LLMClient, initial_text: str = DEFAULT_INITIAL_TEXT) -> None:
        self._llm = llm
        self.text = initial_text

    def update(self, event: Event) -> None:
        self.text = self._llm.chat(
            _UPDATE_PROMPT.format(
                prev=self.text,
                tick=event.tick,
                actor=event.actor,
                action=event.action,
                target=event.target,
                visibility=event.visibility,
                description=event.description,
            )
        ).strip()

    def answer(self, probe: Probe) -> str:
        return self._llm.chat(_ANSWER_PROMPT.format(text=self.text, question=probe.text)).strip()
