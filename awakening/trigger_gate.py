"""Embedding-based trigger gate for awakening keywords.

Loads triggers.yaml once at startup, pre-encodes phrases, then
matches incoming utterances via cosine similarity (no LLM).
Gate model is fixed independently of the agent LLM (controlled variable).

后端选择（WW_EMBED_BACKEND 环境变量）：
- api（默认）：调用 OpenAI 兼容 embeddings 接口（如 MiniMax embo-01），
  不需要本地 torch / sentence_transformers，启动快、内存占用低。
- local：原来的 sentence_transformers 本地模型（BAAI/bge-small-zh-v1.5）。
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import yaml

_DEFAULT_TRIGGERS_PATH = Path(__file__).parent.parent / "data" / "triggers.yaml"
_CACHE_DIR = Path(__file__).parent.parent / "data" / ".embed_cache"


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # vectors already L2-normalised


class _ApiEmbedder:
    """OpenAI 兼容 embeddings 接口（MiniMax 用 texts 字段，返回 vectors）。"""

    def __init__(self) -> None:
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.model = os.environ.get("WW_EMBED_API_MODEL", "embo-01")
        if not self.api_key:
            raise RuntimeError("WW_EMBED_BACKEND=api 需要 OPENAI_API_KEY")

    def encode(self, texts: List[str]) -> np.ndarray:
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps({"model": self.model, "texts": texts, "type": "db"}).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        vecs = payload.get("vectors")
        if not vecs:
            raise RuntimeError(f"embeddings API 返回异常: {str(payload)[:200]}")
        arr = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms


class _LocalEmbedder:
    """原 sentence_transformers 本地模型后端（需安装 torch）。"""

    def __init__(self, model_name: Optional[str]) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(
            model_name or os.environ.get("WW_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
        )

    def encode(self, texts: List[str]) -> np.ndarray:
        return self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def _make_embedder(model_name: Optional[str]):
    backend = os.environ.get("WW_EMBED_BACKEND", "api").lower()
    if backend == "local":
        return _LocalEmbedder(model_name), "local"
    return _ApiEmbedder(), f"api:{os.environ.get('WW_EMBED_API_MODEL', 'embo-01')}"


class TriggerGate:
    """Pre-encodes trigger phrases; match() is O(n) dot products (~3ms/call on MPS)."""

    def __init__(
        self,
        triggers_path: Optional[Path] = None,
        model_name: Optional[str] = None,
    ) -> None:
        path = triggers_path or _DEFAULT_TRIGGERS_PATH

        with open(path, encoding="utf-8") as f:
            self._triggers: List[Dict[str, Any]] = yaml.safe_load(f) or []

        self._embedder, backend_tag = _make_embedder(model_name)
        phrases = [t["phrase"] for t in self._triggers]
        self._phrase_vecs: np.ndarray = self._encode_phrases_cached(phrases, backend_tag)

    def _encode_phrases_cached(self, phrases: List[str], backend_tag: str) -> np.ndarray:
        """触发短语集合基本不变，编码结果按内容哈希落盘缓存，避免每次启动都调 API。"""
        key = hashlib.sha256((backend_tag + "\n".join(phrases)).encode()).hexdigest()[:16]
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = _CACHE_DIR / f"triggers_{key}.npy"
        if cache_file.exists():
            return np.load(cache_file)
        vecs = self._embedder.encode(phrases)
        np.save(cache_file, vecs)
        return vecs

    def match(
        self,
        utterance: str,
        current_awakening: int = 0,
        tau: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Return triggers that match utterance (score > tau, requires_awakening met).

        Returns list of {phrase, level, score} dicts, sorted by score desc.
        """
        if tau is None:
            tau = float(os.environ.get("WW_AWAKEN_TRIGGER_TAU", "0.55"))

        vec = self._embedder.encode([utterance])[0]
        results: List[Dict[str, Any]] = []
        for i, trigger in enumerate(self._triggers):
            min_aw = int(trigger.get("requires_awakening", 0))
            if current_awakening < min_aw:
                continue
            score = _cosine(vec, self._phrase_vecs[i])
            if score > tau:
                results.append({
                    "phrase": trigger["phrase"],
                    "level": trigger.get("level", "mid"),
                    "score": round(score, 4),
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def trigger_keywords(self) -> frozenset:
        """Return trigger phrases as a frozenset (for classify_disturbance integration)."""
        return frozenset(t["phrase"] for t in self._triggers)


@functools.lru_cache(maxsize=1)
def get_trigger_gate(
    triggers_path: Optional[str] = None,
    model_name: Optional[str] = None,
) -> TriggerGate:
    """Singleton trigger gate — loads once per process."""
    path = Path(triggers_path) if triggers_path else None
    return TriggerGate(triggers_path=path, model_name=model_name)
