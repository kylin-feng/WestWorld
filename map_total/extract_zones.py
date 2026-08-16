"""一次性脚本：从西部世界 TMX 的 zones 对象层提取地点骨架。

用法（仓库根目录）：
    python examples/west_world_test/map_total/extract_zones.py > /tmp/zones_skeleton.yaml
产出骨架 YAML，供人工补全为 data/map/locations.yaml。可重跑。
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

TMX_PATH = Path(__file__).parent / "西部世界游戏地图.tmx"
# zones 层已知数据问题的修正表：object id -> 正确名称（None 表示忽略该对象）
NAME_FIXES = {
    959: None,            # 无名点对象，非地点
    969: None, 970: None, 971: None, 972: None, 974: None, 977: None,  # 甜水镇内无名点
    1015: None,           # 无名点对象
    982: "甜水镇医院",     # 属性名 typo：区域mingc
    1000: None,           # "后方控制区"重复点，保留 998
}


def extract() -> list[dict]:
    root = ET.parse(TMX_PATH).getroot()
    zones = next(og for og in root.findall("objectgroup") if og.get("name") == "zones")
    rows = []
    for obj in zones.findall("object"):
        oid = int(obj.get("id"))
        props = {p.get("name"): p.get("value") for p in obj.findall("./properties/property")}
        name = props.get("区域名称") or props.get("区域mingc")
        if oid in NAME_FIXES:
            name = NAME_FIXES[oid]
        if not name:
            print(f"# 跳过无名对象 id={oid}", file=sys.stderr)
            continue
        rows.append({
            "tmx_object_id": oid,
            "name": name,
            "bbox": [round(float(obj.get("x")), 1), round(float(obj.get("y")), 1),
                     round(float(obj.get("width") or 0), 1), round(float(obj.get("height") or 0), 1)],
        })
    return rows


if __name__ == "__main__":
    print(yaml.safe_dump(extract(), allow_unicode=True, sort_keys=False))
