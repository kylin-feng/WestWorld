"""地图真值的加载、校验与查询。locations.yaml 是唯一真值源。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import yaml


@dataclass
class Location:
    id: str
    name: str
    region: str
    type: str
    active: bool
    bbox: List[float]
    adjacency: List[str]
    description: str = ""
    objects: List[Dict[str, Any]] = field(default_factory=list)
    default_occupants: List[str] = field(default_factory=list)

    def visible_objects(self) -> List[Dict[str, Any]]:
        return [o for o in self.objects if not o.get("hidden")]

    def hidden_objects(self) -> List[Dict[str, Any]]:
        return [o for o in self.objects if o.get("hidden")]


class WorldMap:
    def __init__(self, locations: List[Location]) -> None:
        self.locations: Dict[str, Location] = {loc.id: loc for loc in locations}
        self._validate(locations)

    def _validate(self, locations: List[Location]) -> None:
        if len(locations) != len(self.locations):
            raise ValueError("location id 重复")
        for loc in locations:
            for nb in loc.adjacency:
                if nb not in self.locations:
                    raise ValueError(f"{loc.id} 邻接未知地点 {nb}")
                if loc.id not in self.locations[nb].adjacency:
                    raise ValueError(f"邻接不对称: {loc.id} -> {nb}")

    def get(self, location_id: str) -> Location:
        return self.locations[location_id]

    def active_ids(self) -> set:
        return {loc.id for loc in self.locations.values() if loc.active}

    def neighbors(self, location_id: str, active_only: bool = True) -> List[str]:
        nbs = self.get(location_id).adjacency
        if active_only:
            nbs = [n for n in nbs if self.get(n).active]
        return list(nbs)

    def can_move(self, src: str, dst: str) -> Tuple[bool, str]:
        if dst not in self.locations:
            return False, f"不存在名为 {dst} 的地方"
        if src not in self.locations:
            return False, f"不存在名为 {src} 的出发地"
        if dst not in self.get(src).adjacency:
            return False, f"{self.get(dst).name} 与当前位置不相邻"
        if not self.get(dst).active:
            return False, f"通往{self.get(dst).name}的路被封锁了"
        return True, ""


def load_world_map(path: str) -> WorldMap:
    with open(path, "r", encoding="utf-8") as f:
        rows = yaml.safe_load(f)
    return WorldMap([Location(**row) for row in rows])


def default_map_path() -> str:
    """data/map/locations.yaml 的稳健绝对路径（锚定在 example 根，loader.py 上一级）。"""
    return str(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "map", "locations.yaml"))


@lru_cache(maxsize=None)
def get_world_map(path: Optional[str] = None) -> WorldMap:
    """缓存的地图访问器：同一路径只加载一次，返回共享只读实例。

    插件热路径（每 agent / 每 plugin）用它替代各自 load，避免地图被重复加载 N 次。
    WorldMap 是只读真值，agent 只改自己的 state，不改地图，故共享安全。
    """
    return load_world_map(path or default_map_path())
