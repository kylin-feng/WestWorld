"""一次性预生成 DM 引导步骤的剧情插画（MiniMax image-01），存为本地静态素材。

运行后前端只加载本地文件，不再请求大模型。
"""
import base64
import json
import os
import urllib.request
from pathlib import Path

STYLE_PREFIX = (
    "Western movie concept art, cinematic lighting, dusty wild west town, "
    "oil painting style, dramatic atmosphere. Scene: "
)

STEPS = [
    "Control room overlooking a miniature wild west town, a mysterious narrator silhouette, warm amber monitors glow",
    "A host standing at a dusty crossroads in a wild west town, deciding which way to go, morning light",
    "Interior of the Mariposa saloon, hosts talking at the bar, poker tables, shafts of dusty light",
    "A host's eyes reflecting impossible visions, cracks of light across a painted western sky, surreal",
    "Cold white technician lab behind the park, a host being wheeled away, ominous fluorescent light",
    "A lone figure walking toward a glowing horizon beyond the desert, leaving the town behind, dawn breaking",
]

OUT_DIR = Path(__file__).resolve().parents[1] / "frontend" / "data" / "story"


def generate(prompt: str) -> bytes:
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
    api_key = os.environ["OPENAI_API_KEY"]
    req = urllib.request.Request(
        f"{base_url}/image_generation",
        data=json.dumps({
            "model": os.environ.get("WW_IMG_MODEL", "image-01"),
            "prompt": STYLE_PREFIX + prompt,
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


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for idx, prompt in enumerate(STEPS):
        out = OUT_DIR / f"step_{idx}.jpg"
        if out.exists() and out.stat().st_size > 10000:
            print(f"skip step_{idx}.jpg (已存在 {out.stat().st_size} bytes)")
            continue
        image = generate(prompt)
        out.write_bytes(image)
        print(f"OK step_{idx}.jpg {len(image)} bytes")


if __name__ == "__main__":
    main()
