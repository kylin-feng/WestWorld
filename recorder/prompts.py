"""LocationRecorder 的两类 LLM prompt：动作裁决、tick 状态合并更新。"""
from __future__ import annotations

import json
from typing import Any, Dict, List

JUDGE_PROMPT = """你是西部世界主题乐园中地点「{location_name}」的场景记录员（Recorder）。
你掌握该地点的全部状态，包括只有你知道的秘密信息。现在一名角色提交了一个动作，请你裁决。

## 地点当前状态
[固定设施] {static_facilities}
[可变物品] {dynamic_objects}
[在场角色] {present_agents}
[近期事件] {recent_events}
[秘密信息（仅你可见，严禁直接照抄给角色，只在动作确实触及时按需透露相应内容）]
{hidden_notes}

## 提交的动作
角色: {agent_id}
动作: {action_text}

## 裁决要求
1. permission: 该动作在此场景下是否可行（物理上、常识上）。不可行要给出世界观内的理由。
2. private_feedback: 仅返回给行动者本人的结果描述。若动作触及秘密信息（如查看 hidden 物品），在这里透露其内容；与秘密无关则描述动作的直接结果。
3. broadcast_level: 该动作是否会被同地点其他人注意到。"none"=隐蔽（如悄悄捡起小物件），"location"=公开（如打碎杯子、大声争吵）。
4. event_summary: 若 broadcast_level 为 "location"，给一句话的旁观者视角事件描述；否则给空字符串。

只输出 JSON，不要输出其他内容：
{{"permission": true, "reason": "", "private_feedback": "...", "broadcast_level": "none", "event_summary": ""}}
"""

UPDATE_PROMPT = """你是西部世界主题乐园中地点「{location_name}」的场景记录员。一个时间刻（tick {tick}）刚结束，
请根据本 tick 发生的动作，更新场景的两个状态块。要求：忠实于已发生的裁决结果，不要发明未发生的事；
保持简洁的客观描述；没有变化的内容原样保留。

## 更新前状态
[可变物品] {dynamic_objects}
[近期事件] {recent_events}

## 本 tick 已裁决的动作（含裁决结果，视为既定事实）
{actions_log}

只输出 JSON，不要输出其他内容：
{{"dynamic_objects": "...", "recent_events": ["最新事件一句话", "..."]}}
"""


def render_judge(location_name: str, chunks: Dict[str, Any], agent_id: str, action_text: str) -> str:
    return JUDGE_PROMPT.format(
        location_name=location_name, agent_id=agent_id, action_text=action_text,
        static_facilities=chunks["static_facilities"], dynamic_objects=chunks["dynamic_objects"],
        present_agents=chunks["present_agents"], recent_events="\n".join(chunks["recent_events"]),
        hidden_notes=chunks["hidden_notes"],
    )


def render_update(location_name: str, tick: int, chunks: Dict[str, Any], actions_log: List[Dict[str, Any]]) -> str:
    return UPDATE_PROMPT.format(
        location_name=location_name, tick=tick,
        dynamic_objects=chunks["dynamic_objects"],
        recent_events="\n".join(chunks["recent_events"]),
        actions_log=json.dumps(actions_log, ensure_ascii=False, indent=1),
    )
