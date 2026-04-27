from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from _models import CaptionPos


@lru_cache(maxsize=4)
def _resolve_font(weight: str = "regular") -> Path:
    spec = "Noto Sans CJK SC" + (":weight=bold" if weight == "bold" else "")
    out = subprocess.run(
        ["fc-match", "-f", "%{file}", spec],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return Path(out)


def _scale_and_crop(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(img, target, method=Image.Resampling.LANCZOS)


def _wrap_caption(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        bbox = font.getbbox(trial)
        if (bbox[2] - bbox[0]) > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def render_scene(
    background_path: Path,
    caption: str | None,
    caption_position: CaptionPos,
    resolution: tuple[int, int],
    out_path: Path,
) -> None:
    bg = Image.open(background_path).convert("RGB")
    frame = _scale_and_crop(bg, resolution)

    if caption:
        draw = ImageDraw.Draw(frame)
        font_size = max(40, resolution[1] // 18)
        font = ImageFont.truetype(str(_resolve_font("bold")), font_size)
        margin = resolution[0] // 20
        max_w = resolution[0] - 2 * margin
        lines = _wrap_caption(caption, font, max_w)
        line_h = font_size + 10
        block_h = line_h * len(lines)

        if caption_position == "top":
            y0 = margin
        elif caption_position == "center":
            y0 = (resolution[1] - block_h) // 2
        else:
            y0 = resolution[1] - margin - block_h

        for i, line in enumerate(lines):
            bbox = font.getbbox(line)
            line_w = bbox[2] - bbox[0]
            x = (resolution[0] - line_w) // 2
            y = y0 + i * line_h
            draw.text(
                (x, y), line, font=font,
                fill=(255, 255, 255),
                stroke_width=5,
                stroke_fill=(0, 0, 0),
            )

    frame.save(out_path, "PNG")
