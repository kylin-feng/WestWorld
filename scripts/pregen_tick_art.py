"""按幕预生成剧情插画（frontend/data/story/tick_N.jpg）。

读取 data/story_script.json，为每一幕生成一张 16:9 西部油画风场景图。
增量执行：已存在的幕跳过，可随时重跑补齐新生成的幕。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path

WESTWORLD_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = WESTWORLD_ROOT / "data" / "story_script.json"
OUT_DIR = WESTWORLD_ROOT / "frontend" / "data" / "story"

STYLE_PREFIX = (
    "Western movie concept art, cinematic wide shot, dusty wild west town, "
    "oil painting style, dramatic atmosphere. Scene: "
)

SEGMENT_NAMES = ["清晨", "上午", "正午", "下午", "傍晚", "夜晚"]
SEGMENT_LIGHT = {
    "清晨": "sunrise golden mist", "上午": "bright morning light",
    "正午": "harsh noon sunlight", "下午": "warm afternoon glow",
    "傍晚": "sunset orange sky", "夜晚": "moonlit night, lantern light",
}


def _image_generate(prompt: str) -> bytes:
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
    api_key = os.environ["OPENAI_API_KEY"]
    req = urllib.request.Request(
        f"{base_url}/image_generation",
        data=json.dumps({
            "model": os.environ.get("WW_IMG_MODEL", "image-01"),
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "response_format": "base64",
            "n": 1,
        }).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = json.loads(resp.read())
    images = (payload.get("data") or {}).get("image_base64") or []
    if not images:
        raise RuntimeError(f"返回异常: {str(payload)[:200]}")
    return base64.b64decode(images[0])


def _tick_prompt(tick: int, block: dict) -> str:
    segment = SEGMENT_NAMES[tick % 6]
    light = SEGMENT_LIGHT[segment]
    # 取本幕几条行动描述作为画面元素（detail 是中文，拼一个英文画面提示更稳）
    plans = list((block.get("plans") or {}).values())[:13]
    n_talk = sum(1 for p in plans if p.get("action") == "talk")
    n_move = sum(1 for p in plans if p.get("action") == "move")
    beats = []
    if n_talk:
        beats.append("characters in quiet tense conversation")
    if n_move:
        beats.append("a figure walking through the dusty street")
    if tick >= 9:
        beats.append("an unsettling surreal crack in the sky, subtle glitch in reality")
    elif tick >= 6:
        beats.append("a character pausing with a haunted, doubtful expression")
    elif tick >= 3:
        beats.append("a subtle sense of deja vu, dreamlike haze at the edges")
    beat_text = ", ".join(beats) or "peaceful daily routine in the frontier town"
    return f"{light}, {beat_text}, wild west frontier town of Sweetwater, no text"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    script = json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))
    ticks = sorted((int(k) for k in (script.get("ticks") or {})))
    for tick in ticks:
        out = OUT_DIR / f"tick_{tick}.jpg"
        if out.exists() and out.stat().st_size > 10000:
            print(f"skip tick_{tick}.jpg（已存在）", flush=True)
            continue
        prompt = STYLE_PREFIX + _tick_prompt(tick, script["ticks"][str(tick)])
        for attempt in range(3):
            try:
                image = _image_generate(prompt)
                out.write_bytes(image)
                print(f"OK tick_{tick}.jpg {len(image)} bytes", flush=True)
                break
            except Exception as exc:
                print(f"tick {tick} 第 {attempt + 1} 次生图失败: {exc}", flush=True)
        else:
            print(f"tick {tick} 生图失败，跳过", flush=True)


if __name__ == "__main__":
    main()
