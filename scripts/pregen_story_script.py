"""一次性预生成剧情模式剧本（data/story_script.json）。

每个 tick 一次 LLM 调用，批量生成全部 NPC 的决策与同地对话；
生成器自己用世界地图模拟走位并校验合法性（非法 move 降级为 stay），
保证剧本在引擎里可直接执行。运行时由 scripted_mode.py 读取，NPC 零 LLM 请求。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

WESTWORLD_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WESTWORLD_ROOT.parents[1]))  # OpenStory 根，供 import examples.WestWorld

from examples.WestWorld.worldmap.loader import get_world_map  # noqa: E402

SEGMENT_NAMES = ["清晨", "上午", "正午", "下午", "傍晚", "夜晚"]
VALID_ACTIONS = ("do", "move", "stay", "talk")

ARC_PHASES = [
    (0, 3, "日常循环：一切平静，角色严格按日常习惯行事，台词生活化。"),
    (3, 6, "细微异样：个别接待员出现似曾相识感、梦境片段、莫名的念头，但很快自我掩饰过去。"),
    (6, 9, "裂痕扩大：记忆闪回更频繁，有角色在对话中不小心说出“剧本之外”的话，气氛开始不安。"),
    (9, 12, "觉醒蔓延：多名接待员公开谈论梦境与真实，互相确认“你不是唯一一个”，有人开始计划反抗或逃离。"),
]

PROMPT_TEMPLATE = """你是《西部世界》乐园的编剧。为第 {tick} 幕（{segment}）编写所有接待员/访客的行动与对话。

## 本幕基调
{arc}

## 角色与当前状态
{agent_blocks}

## 编写要求
1. 为每个角色给出 action：
   - "do"：在当前地点做一件事，detail 写一句话的第一人称行为描述（中文，有画面感，30 字内）
   - "stay"：什么都不做
   - "move"：前往相邻地点，target 只能填该角色「可前往」列表中的地点 id
   - "talk"：与同一地点的另一角色深入交谈，target 填对方 id；只有同地角色可以 talk
2. 每个角色给出 thought：一句内心独白（中文，20 字内，贴合本幕基调）
3. 为同地且适合交谈的角色组合写 1-{max_dialogues} 段 dialogues：每段 participants 两个 id，turns 为 4 句交替台词
   （格式：[动作或神态] "台词"，例：[放下酒杯] "你昨晚也梦见了，对吧？"）
4. 对话内容要推进本幕基调，后期阶段让角色谈论梦境、记忆、真实与自由
5. 玩家的行为不可预知，所有剧本内容不得依赖某个特定角色一定在场

只输出 JSON（不要代码块、不要解释）：
{{"plans": {{"角色id": {{"action": "...", "target": "", "detail": "...", "thought": "..."}}, ...}},
 "dialogues": [{{"participants": ["idA", "idB"], "turns": [{{"speaker": "idA", "line": "..."}}, ...]}}]}}"""


def _llm_chat(prompt: str) -> str:
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
    api_key = os.environ["OPENAI_API_KEY"]
    model = os.environ.get("OPENSTORY_MODEL") or os.environ.get("WW_MODEL") or "MiniMax-M2.7-highspeed"
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 8000,
        }).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read())
    return payload["choices"][0]["message"]["content"]


def _salvage_truncated(fragment: str) -> dict:
    """抢救被 max_tokens 截断的 JSON：截到最后一个完整值边界，补齐未闭合的引号与括号。"""
    # 逐字符扫描，记录字符串状态与括号栈，找到最后一个"完整值结束"的位置
    stack: list = []
    in_str = False
    escape = False
    last_safe = -1
    for i, ch in enumerate(fragment):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            if stack and stack[-1] in "{[":
                last_safe = i  # 某个完整对象/数组闭合
        elif ch == "," and stack:
            last_safe = i  # 值边界，后面可安全截断
    if not stack or last_safe < 0:
        raise ValueError("无法抢救截断输出")
    cut = fragment[:last_safe + 1].rstrip().rstrip(",")
    closers = {"{": "}", "[": "]"}
    # 重新扫描 cut，计算还需要补哪些闭合符
    stack2: list = []
    in_str = False
    escape = False
    for ch in cut:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack2.append(ch)
        elif ch in "}]" and stack2:
            stack2.pop()
    if in_str:
        cut += '"'
    cut += "".join(closers[c] for c in reversed(stack2))
    return json.loads(cut)


def _parse_json(text: str) -> dict:
    import ast

    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    if start < 0:
        raise ValueError("输出中没有 JSON 对象")
    fragment = text[start:]
    # 先标准 JSON（只取第一个完整对象，容忍尾部多余内容），再退到 Python 字面量（单引号等）
    try:
        obj, _ = json.JSONDecoder().raw_decode(fragment)
    except json.JSONDecodeError:
        try:
            end = fragment.rfind("}")
            if end <= 0:
                raise ValueError("输出中没有完整 JSON 对象")
            obj = ast.literal_eval(fragment[:end + 1])
        except Exception:
            obj = _salvage_truncated(fragment)
    if not isinstance(obj, dict):
        raise ValueError("解析结果不是 JSON 对象")
    return obj


def _arc_for(tick: int) -> str:
    for lo, hi, text in ARC_PHASES:
        if lo <= tick < hi:
            return text
    return ARC_PHASES[-1][2]


def main() -> None:
    ticks_total = int(os.environ.get("WW_SCRIPT_TICKS", "12"))
    out_path = WESTWORLD_ROOT / "data" / "story_script.json"

    profiles = {}
    for line in open(WESTWORLD_ROOT / "data/agents/profiles_sim.jsonl", encoding="utf-8"):
        row = json.loads(line)
        profiles[row["id"]] = row
    positions = {}
    for line in open(WESTWORLD_ROOT / "data/agents/states_sim.jsonl", encoding="utf-8"):
        row = json.loads(line)
        positions[row["id"]] = row.get("location", "")
    world = get_world_map()
    agent_ids = sorted(profiles)

    script = {"version": 1, "ticks": {}}
    if out_path.exists():
        try:
            script = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            script = {"version": 1, "ticks": {}}
    script.setdefault("ticks", {})

    for tick in range(ticks_total):
        segment = SEGMENT_NAMES[tick % 6]
        if str(tick) in script["ticks"]:
            # 断点续跑：已有幕直接应用其走位，保持位置模拟连续
            for aid, plan in (script["ticks"][str(tick)].get("plans") or {}).items():
                if aid in positions and plan.get("action") == "move":
                    ok, _ = world.can_move(positions[aid], plan.get("target", ""))
                    if ok:
                        positions[aid] = plan["target"]
            print(f"tick {tick}（{segment}）跳过（已存在）")
            continue
        agent_blocks = []
        for aid in agent_ids:
            profile = profiles[aid]
            loc = positions[aid]
            loop = profile.get("daily_loop") or []
            seg = loop[tick % 6] if len(loop) > tick % 6 else {}
            neighbors = [f"{n}（{world.get(n).name}）" for n in world.neighbors(loc)]
            co_located = [f"{o}（{profiles[o]['name']}）" for o in agent_ids if o != aid and positions[o] == loc]
            agent_blocks.append(
                f"- {aid}（{profile['name']}，{'接待员' if profile.get('agent_type') == 'host' else '访客'}）\n"
                f"  性格：{str(profile.get('personality', ''))[:80]}\n"
                f"  当前位置：{loc}（{world.get(loc).name}）；此时段习惯：{seg.get('intent', '按日常行事')}\n"
                f"  可前往：{', '.join(neighbors) or '（无处可去）'}；同地角色：{', '.join(co_located) or '（独自一人）'}"
            )

        prompt = PROMPT_TEMPLATE.format(
            tick=tick, segment=segment, arc=_arc_for(tick),
            agent_blocks="\n".join(agent_blocks), max_dialogues=3,
        )

        raw = ""
        data = None
        hint = ""
        for attempt in range(3):
            try:
                raw = _llm_chat(prompt + hint)
                data = _parse_json(raw)
                # 有同地角色却一段对话都没有时，带提示重试一次
                has_co_located = len({positions[aid] for aid in agent_ids}) < len(agent_ids)
                if not (data.get("dialogues") or []) and has_co_located and attempt < 2:
                    hint = "\n\n上次输出没有任何对话。请至少为同地角色写 1 段 4 句的交替对话。"
                    data = None
                    continue
                break
            except Exception as exc:
                print(f"tick {tick} 第 {attempt + 1} 次生成失败: {exc}")
                hint = "\n\n上次输出无法解析，请只输出合法 JSON。"
        if data is None:
            raise RuntimeError(f"tick {tick} 生成失败")

        # ── 校验与修复：非法 move 降级 stay，talk/对话仅限同地 ──
        plans = {}
        for aid in agent_ids:
            plan = (data.get("plans") or {}).get(aid)
            if not isinstance(plan, dict):
                plan = {}
            action = plan.get("action") if plan.get("action") in VALID_ACTIONS else "stay"
            target = str(plan.get("target", "") or "")
            if action == "move":
                ok, _ = world.can_move(positions[aid], target)
                if not ok:
                    action, target = "stay", ""
            if action == "talk" and positions.get(target) != positions[aid]:
                action, target = "do", ""
            plans[aid] = {
                "action": action,
                "target": target,
                "detail": str(plan.get("detail", "") or "")[:120],
                "thought": str(plan.get("thought", "") or "")[:80],
            }

        dialogues = []
        for row in (data.get("dialogues") or [])[:3]:
            if not isinstance(row, dict):
                continue
            parts = row.get("participants") or []
            if not isinstance(parts, list) or len(parts) != 2 or parts[0] == parts[1]:
                continue
            a, b = str(parts[0]), str(parts[1])
            if a not in positions or b not in positions or positions[a] != positions[b]:
                continue
            turns = [
                {"speaker": str(t["speaker"]), "line": str(t["line"])[:120]}
                for t in row.get("turns") or []
                if isinstance(t, dict) and t.get("speaker") in (a, b) and t.get("line")
            ]
            if len(turns) < 2:
                continue
            # 确保配对能产生 talk 意图，barrier 才会触发改组对话
            if plans[a]["action"] != "talk" and plans[b]["action"] != "talk":
                plans[a].update({"action": "talk", "target": b, "detail": ""})
            dialogues.append({"participants": [a, b], "turns": turns})

        # 应用移动，推进走位模拟
        for aid, plan in plans.items():
            if plan["action"] == "move":
                positions[aid] = plan["target"]

        script["ticks"][str(tick)] = {"plans": plans, "dialogues": dialogues}
        # 每幕落盘，失败后可断点续跑
        out_path.write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
        moves = sum(1 for p in plans.values() if p["action"] == "move")
        print(f"tick {tick}（{segment}）OK：{len(plans)} 决策，{moves} 移动，{len(dialogues)} 段对话")

    out_path.write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"剧本已写入 {out_path}（{ticks_total} ticks）")


if __name__ == "__main__":
    main()
