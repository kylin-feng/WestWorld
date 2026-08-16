"""预设剧本模式：NPC 的决策与对话来自离线预生成剧本（data/story_script.json），不走大模型。

- 由 story/run_simulation.py 通过环境变量启用：WW_STORY_SCRIPT 指向剧本文件，
  WW_STORY_RUNTIME_FILE 指向运行时文件（记录本局玩家 agent_id）。
- 玩家角色与超出剧本范围的 tick 回退到实时 LLM。
- 本模块在 Ray pod 内也会被导入，必须只依赖标准库。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

_script_cache: Dict[str, Any] = {"mtime": 0.0, "data": None}
_runtime_cache: Dict[str, Any] = {"mtime": 0.0, "player": ""}

_VALID_ACTIONS = frozenset({"do", "move", "stay", "talk"})


def enabled() -> bool:
    return bool(os.environ.get("WW_STORY_SCRIPT"))


def _load_script() -> Dict[str, Any]:
    path = os.environ.get("WW_STORY_SCRIPT", "")
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _script_cache["data"] is None or mtime != _script_cache["mtime"]:
        try:
            with open(path, encoding="utf-8") as f:
                _script_cache["data"] = json.load(f)
            _script_cache["mtime"] = mtime
        except Exception:
            return {}
    return _script_cache["data"] or {}


def player_agent_id() -> str:
    """本局玩家附身的角色 id（由 set_player 写入运行时文件）。未选玩家时为空。"""
    path = os.environ.get("WW_STORY_RUNTIME_FILE", "")
    if not path:
        return ""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    if mtime != _runtime_cache["mtime"]:
        player = ""
        try:
            with open(path, encoding="utf-8") as f:
                player = str(json.load(f).get("player_agent_id", "") or "")
        except Exception:
            player = ""
        _runtime_cache["player"] = player
        _runtime_cache["mtime"] = mtime
    return _runtime_cache["player"]


def write_player_agent_id(agent_id: str) -> None:
    """story 模式选角后调用：记录玩家角色，供各 pod 内的插件识别。"""
    path = os.environ.get("WW_STORY_RUNTIME_FILE", "")
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"player_agent_id": agent_id}, f, ensure_ascii=False)
    _runtime_cache["player"] = agent_id
    try:
        _runtime_cache["mtime"] = os.path.getmtime(path)
    except OSError:
        pass


def _tick_block(tick: int) -> Dict[str, Any]:
    ticks = _load_script().get("ticks") or {}
    block = ticks.get(str(tick))
    return block if isinstance(block, dict) else {}


def scripted_plan(tick: int, agent_id: str) -> Optional[Dict[str, Any]]:
    """返回该 NPC 本 tick 的预设决策；玩家 / 无剧本 / 未启用时返回 None。"""
    if not enabled() or agent_id == player_agent_id():
        return None
    plan = (_tick_block(tick).get("plans") or {}).get(agent_id)
    if not isinstance(plan, dict):
        return None
    action = plan.get("action")
    recipients = plan.get("recipient_ids")
    return {
        "action": action if action in _VALID_ACTIONS else "stay",
        "target": str(plan.get("target", "") or ""),
        "detail": str(plan.get("detail", "") or ""),
        "recipient_ids": [r for r in recipients if isinstance(r, str)] if isinstance(recipients, list) else [],
        "next_read": ["present_agents", "dynamic_objects"],
        "thought": str(plan.get("thought", "") or ""),
    }


def scripted_dialogue(tick: int, speaker_id: str, target_id: str) -> Optional[List[Dict[str, str]]]:
    """返回该配对本 tick 的预设台词；涉及玩家或无剧本时返回 None（走实时 LLM）。"""
    if not enabled():
        return None
    player = player_agent_id()
    if player and player in (speaker_id, target_id):
        return None
    pair = frozenset((speaker_id, target_id))
    for row in _tick_block(tick).get("dialogues") or []:
        participants = row.get("participants")
        if not isinstance(participants, list) or frozenset(participants) != pair:
            continue
        turns = [
            {"speaker": str(t["speaker"]), "line": str(t["line"])}
            for t in row.get("turns") or []
            if isinstance(t, dict) and t.get("speaker") and t.get("line")
        ]
        return turns or None
    return None


# ── 场景裁决 / 监管 / 反思的预生成或快速回退 ────────────────────────────────

# 脚本中可预置的裁决字段；缺失时由 _FAST_JUDGEMENT 补全。
_JUDGEMENT_KEYS = frozenset({
    "permission", "reason", "private_feedback", "broadcast_level",
    "event_summary", "ambient",
})

_FAST_JUDGEMENT = {
    "permission": True,
    "reason": "",
    "private_feedback": "动作已顺利完成。",
    "broadcast_level": "none",
    "event_summary": "",
    "ambient": "",
}


def scripted_resolution(
    tick: int,
    location_id: str,
    agent_id: str,
    action_text: str = "",
    action_type: str = "do",
) -> Optional[Dict[str, Any]]:
    """返回本 tick 本地点该角色的预生成场景裁决；无剧本/未启用时返回 None。

    若启用了剧本模式但没有预生成裁决，则返回一个安全的快速模板裁决，
    使剧本模式不再为每个动作调用 LLM 进行场景解析。
    """
    if not enabled():
        return None
    block = _tick_block(tick)
    resolutions = block.get("resolutions") or {}
    loc_block = resolutions.get(location_id) or {}
    if isinstance(loc_block, list):
        for row in loc_block:
            if isinstance(row, dict) and row.get("agent_id") == agent_id:
                judgement = {**_FAST_JUDGEMENT, **{
                    k: v for k, v in row.items() if k in _JUDGEMENT_KEYS
                }}
                return {**_FAST_JUDGEMENT, "status": "resolved", **judgement}
    # 剧本模式默认：用模板快速裁决，不走实时 LLM
    fast = dict(_FAST_JUDGEMENT)
    fast["status"] = "resolved"
    fast["action_type"] = action_type
    fast["action_text"] = action_text
    return fast


def overseer_enabled_in_scripted_mode() -> bool:
    """剧本模式下默认关闭实时 Overseer（省掉 embedding+LLM 监管），可用 WW_SCRIPTED_OVERSEER=on 强制开启。"""
    if not enabled():
        return True
    return os.environ.get("WW_SCRIPTED_OVERSEER", "off").lower() in ("on", "1", "true")


def reflect_summary(tick: int, agent_id: str) -> Optional[str]:
    """剧本模式下返回预生成的反思总结；None 表示走默认逻辑或不做总结。"""
    if not enabled():
        return None
    summaries = (_tick_block(tick).get("reflect_summaries") or {})
    summary = summaries.get(agent_id)
    return str(summary) if summary else ""
