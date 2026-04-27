from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CaptionPos = Literal["top", "center", "bottom"]
Aspect = Literal["16:9", "9:16"]
KenBurns = Literal["none", "in", "out", "left", "right"]
Transition = Literal["cut", "crossfade"]

ASPECT_TO_RES: dict[Aspect, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}


class Scene(BaseModel):
    duration_s: float = Field(gt=0, le=30)
    background_image: str
    caption: str | None = None
    caption_position: CaptionPos = "bottom"
    ken_burns: KenBurns = "in"


class VideoPlan(BaseModel):
    title: str
    aspect: Aspect = "16:9"
    fps: int = Field(default=30, ge=15, le=60)
    scenes: list[Scene] = Field(min_length=1, max_length=10)
    transition: Transition = "crossfade"
    transition_duration_s: float = Field(default=0.5, ge=0.1, le=2.0)

    @property
    def resolution(self) -> tuple[int, int]:
        return ASPECT_TO_RES[self.aspect]

    @model_validator(mode="after")
    def _validate_transition_against_scene_durations(self) -> "VideoPlan":
        if self.transition == "crossfade" and len(self.scenes) > 1:
            min_scene = min(s.duration_s for s in self.scenes)
            if self.transition_duration_s >= min_scene - 0.1:
                raise ValueError(
                    f"transition_duration_s ({self.transition_duration_s}) must be "
                    f"less than the shortest scene minus 0.1s "
                    f"(shortest = {min_scene}s)"
                )
        return self
