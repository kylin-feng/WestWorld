"""Model client protocols."""
from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def chat(self, prompt: str) -> str: ...


class ImageGen(Protocol):
    def create_initial(self, prompt: str) -> str: ...

    def apply_event(self, previous_image: str, prompt: str) -> str: ...


class VLM(Protocol):
    def ask(self, image_handle: str, question: str) -> str: ...
