from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CaptionPos = Literal["top", "center", "bottom"]
Aspect = Literal["16:9", "9:16"]

ASPECT_TO_RES: dict[Aspect, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}


class Scene(BaseModel):
    duration_s: float = Field(gt=0, le=30)
    background_image: str
    caption: str | None = None
    caption_position: CaptionPos = "bottom"


class VideoPlan(BaseModel):
    title: str
    aspect: Aspect = "16:9"
    fps: int = Field(default=30, ge=15, le=60)
    scenes: list[Scene] = Field(min_length=1, max_length=10)

    @property
    def resolution(self) -> tuple[int, int]:
        return ASPECT_TO_RES[self.aspect]
