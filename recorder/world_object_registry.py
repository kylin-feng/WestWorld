"""World-level object registry: single source of truth for all objects across locations."""
from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

# 不可被 patch 覆盖的保留字段
META_FIELDS = {"object_id", "name", "hidden", "destroyed", "provenance", "location_id"}


class WorldObjectRegistry:
    """所有地点所有对象的唯一真值源 + append-only ledger。"""

    def __init__(self) -> None:
        self._objects: Dict[str, Dict[str, Any]] = {}
        self._next_id = 0
        self.ledger: List[Dict[str, Any]] = []
        self._seeded = False
        self._seeded_locations: set = set()
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self):
        """Keep a multi-step validation and mutation sequence atomic."""
        with self._lock:
            yield

    # ---- 写 ----
    def create(self, name: str, location_id: str, by: str, tick: Optional[int],
               action: str, fields: Dict[str, Any], hidden: bool = False,
               held_by: str = "") -> str:
        with self._lock:
            oid = f"obj_{self._next_id}"
            self._next_id += 1
            row: Dict[str, Any] = {
                "object_id": oid,
                "name": name,
                "location_id": location_id,
                "held_by": held_by,
                "state": "状态正常",
                "hidden": bool(hidden),
                "destroyed": False,
                "provenance": {"created_by": by, "created_tick": tick, "created_action": action},
            }
            for key, value in fields.items():
                if key not in META_FIELDS and key not in ("held_by",):
                    row[key] = value
            self._objects[oid] = row
            self._log("create", oid, None, copy.deepcopy(row), by, tick)
            return oid

    def apply_patch(
        self, object_id: str, updates: Dict[str, Any],
        by: Optional[str] = None, tick: Optional[int] = None,
    ) -> None:
        with self._lock:
            if object_id not in self._objects:
                raise KeyError(f"unknown object_id: {object_id}")
            row = self._objects[object_id]
            before = copy.deepcopy(row)
            for key, value in updates.items():
                if key in META_FIELDS:
                    continue
                row[key] = value
            self._log("patch", object_id, before, copy.deepcopy(row), by, tick)

    def destroy(self, object_id: str, by: str, tick: Optional[int]) -> None:
        with self._lock:
            if object_id not in self._objects:
                raise KeyError(f"unknown object_id: {object_id}")
            row = self._objects[object_id]
            before = copy.deepcopy(row)
            row["destroyed"] = True
            self._log("destroy", object_id, before, copy.deepcopy(row), by, tick)

    # ---- 读 ----
    def get(self, object_id: str) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._objects[object_id])

    def has(self, object_id: str) -> bool:
        with self._lock:
            return object_id in self._objects

    def objects_at(self, location_id: str, include_hidden: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            rows = [
                r for r in self._objects.values()
                if r["location_id"] == location_id and not r["destroyed"]
                and (include_hidden or not r["hidden"])
            ]
            return [copy.deepcopy(r) for r in rows]

    @property
    def _AWAKENING_UNCANNY_THRESHOLD(self) -> int:
        import os
        return int(os.environ.get("WW_UNCANNY_THRESHOLD", "30"))

    def objects_at_for_viewer(
        self,
        location_id: str,
        viewer_discovered: set,
        viewer_awakening: int = 0,
    ) -> List[Dict[str, Any]]:
        """返回对特定 viewer 可见的对象列表（per-agent 过滤）。

        规则：
        - 非 hidden 对象：对所有 viewer 可见。
        - hidden 对象：仅当 object_id ∈ viewer_discovered 时对该 viewer 可见。
        - 非 hidden 且有 secret 字段：viewer_awakening 达阈值时在副本中附 _uncanny 键。
        不改变 registry 内部状态——纯读路径。
        """
        with self._lock:
            result = []
            for r in self._objects.values():
                if r["location_id"] != location_id or r["destroyed"]:
                    continue
                if r["hidden"] and r["object_id"] not in viewer_discovered:
                    continue
                row = copy.deepcopy(r)
                if (
                    not r["hidden"]
                    and row.get("secret")
                    and viewer_awakening >= self._AWAKENING_UNCANNY_THRESHOLD
                ):
                    row["_uncanny"] = row["secret"]
                result.append(row)
            return result

    def relocate_holdings(self, agent_id: str, to_location: str, tick: Optional[int] = None) -> None:
        with self._lock:
            for row in self._objects.values():
                if row["held_by"] == agent_id and not row["destroyed"]:
                    before = copy.deepcopy(row)
                    row["location_id"] = to_location
                    self._log("relocate", row["object_id"], before, copy.deepcopy(row), agent_id, tick)

    def seed_from_world(self, world_map: Any) -> None:
        with self._lock:
            if self._seeded:
                return
            for lid in sorted(world_map.active_ids()):
                location = world_map.get(lid)
                for item in location.objects:
                    fields = {"state": item.get("note", "状态正常")}
                    if item.get("secret"):
                        fields["secret"] = item["secret"]
                    self.create(
                        name=item["name"], location_id=lid, by="__seed__", tick=None,
                        action="__seed__", fields=fields, hidden=bool(item.get("hidden")),
                    )
            self._seeded = True

    def is_location_seeded(self, location_id: str) -> bool:
        with self._lock:
            return location_id in self._seeded_locations

    def mark_location_seeded(self, location_id: str) -> None:
        with self._lock:
            self._seeded_locations.add(location_id)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "objects": [copy.deepcopy(r) for r in self._objects.values()],
                "ledger": copy.deepcopy(self.ledger),
                "next_id": self._next_id,
                "seeded": self._seeded,
                "seeded_locations": sorted(self._seeded_locations),
            }

    def ledger_size(self) -> int:
        with self._lock:
            return len(self.ledger)

    def ledger_since(self, index: int) -> List[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self.ledger[index:])

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """Restore a previously captured registry snapshot."""
        with self._lock:
            objects = snapshot.get("objects", [])
            if not isinstance(objects, list):
                raise ValueError("registry snapshot objects must be a list")
            restored = {}
            for row in objects:
                if not isinstance(row, dict) or not row.get("object_id"):
                    raise ValueError("registry snapshot contains an invalid object")
                restored[row["object_id"]] = copy.deepcopy(row)
            self._objects = restored
            self.ledger = copy.deepcopy(snapshot.get("ledger", []))
            inferred_next = max(
                (int(oid.split("_", 1)[1]) + 1 for oid in restored if oid.startswith("obj_")),
                default=0,
            )
            self._next_id = max(int(snapshot.get("next_id", 0)), inferred_next)
            self._seeded = bool(snapshot.get("seeded", False))
            self._seeded_locations = set(snapshot.get("seeded_locations", []))

    def _log(self, op: str, object_id: str, before: Optional[Dict[str, Any]],
             after: Optional[Dict[str, Any]], by: Optional[str], tick: Optional[int]) -> None:
        self.ledger.append({
            "op": op, "object_id": object_id,
            "before": before, "after": after, "by": by, "tick": tick,
        })


_REGISTRY: Optional[WorldObjectRegistry] = None


def get_object_registry() -> WorldObjectRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = WorldObjectRegistry()
    return _REGISTRY


def reset_object_registry() -> None:
    """测试隔离用：清空进程内单例。"""
    global _REGISTRY
    _REGISTRY = None
