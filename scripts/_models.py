from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CaptionPos = Literal["top", "center", "bottom"]
Aspect = Literal["16:9", "9:16"]
KenBurns = Literal["none", "in", "out", "left", "right"]
Transition = Literal["cut", "crossfade"]
TransitionStyle = Literal["fade", "fadeblack", "fadewhite", "dissolve"]

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
    narration_path: str | None = None  # V0.3+: optional per-scene audio (mp3/wav)


class VideoPlan(BaseModel):
    title: str
    aspect: Aspect = "16:9"
    fps: int = Field(default=30, ge=15, le=60)
    scenes: list[Scene] = Field(min_length=1, max_length=10)
    transition: Transition = "crossfade"
    transition_style: TransitionStyle = "fade"
    transition_duration_s: float = Field(default=0.5, ge=0.1, le=2.0)
    # V0.3.1: range tightened from 0.0-1.0 to 0.0-0.3. Higher values cause ffmpeg's
    # tpad+zoompan+xfade chain to deadlock (output video stream plateaus at the
    # duration of one scene regardless of plan total). Empirically reproduced on
    # ffmpeg 6.x with both single-image-per-scene and 9-scene plans. The
    # documented 1.0 upper bound from V0.2.x was a wishful spec — only 0.3 (the
    # default) was ever validated. See CHANGELOG 0.3.1 for the failed -loop 1 -t
    # workaround attempt.
    tail_hold_s: float = Field(default=0.3, ge=0.0, le=0.3)

    @property
    def resolution(self) -> tuple[int, int]:
        return ASPECT_TO_RES[self.aspect]

    @model_validator(mode="after")
    def _validate_transition_against_scene_durations(self) -> "VideoPlan":
        if self.transition == "crossfade" and len(self.scenes) > 1:
            min_scene = min(s.duration_s for s in self.scenes)
            effective = min_scene + self.tail_hold_s
            if self.transition_duration_s >= effective - 0.1:
                raise ValueError(
                    f"transition_duration_s ({self.transition_duration_s}) must be "
                    f"less than the shortest scene + tail_hold_s minus 0.1s "
                    f"(shortest scene = {min_scene}s, tail_hold = {self.tail_hold_s}s, "
                    f"effective = {effective}s)"
                )
        return self
