"""Image-only recorder that evolves the previous image with each event."""
from __future__ import annotations

from typing import Optional

from .llm_client import ImageGen, VLM
from .schema import Event, Probe
from .text_representation import DEFAULT_INITIAL_TEXT

_INITIAL_IMAGE_PROMPT = (
    "Create a fixed-camera, wide but legible overview of the Sweetwater saloon. "
    "This image is the complete initial world state for a visual-state experiment. "
    "Show the bartender behind the bar, the Man in Black near the floor photo, and "
    "Dolores near the table. Keep their clothing and positions visually distinct. "
    "Make every tracked object clearly visible and unoccluded: exactly three intact "
    "empty whiskey glasses, the old photo, wanted poster, player piano, revolver, and "
    "closed door. Preserve object identity, count, character appearance, position, "
    "lighting, and fixed camera composition in later edits. Do not add decorative "
    "duplicates of tracked objects.\n{scene}"
)

_EVENT_EDIT_PROMPT = """Edit the previous world-state image to apply exactly one event.
Preserve every unaffected object, character, count, position, and the fixed camera.
Do not use or infer any hidden textual state beyond what is visible in the previous image
and the event below.

event_id={id} tick={tick} actor={actor} action={action} target={target} visibility={visibility}
Event description: {description}
"""


class ImageRepresentation:
    def __init__(self, image_gen: ImageGen, vlm: VLM, initial_text: str = DEFAULT_INITIAL_TEXT) -> None:
        self._image_gen = image_gen
        self._vlm = vlm
        self._initial_prompt = _INITIAL_IMAGE_PROMPT.format(scene=initial_text)
        self.current_image: Optional[str] = None

    def update(self, event: Event) -> None:
        previous_image = self._ensure_current_image()
        prompt = _EVENT_EDIT_PROMPT.format(
            id=event.id,
            tick=event.tick,
            actor=event.actor,
            action=event.action,
            target=event.target,
            visibility=event.visibility,
            description=event.description,
        )
        self.current_image = self._image_gen.apply_event(previous_image, prompt)

    def _ensure_current_image(self) -> str:
        if self.current_image is None:
            self.current_image = self._image_gen.create_initial(self._initial_prompt)
        return self.current_image

    def answer(self, probe: Probe) -> str:
        return self._vlm.ask(self._ensure_current_image(), probe.text).strip()
