from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _models import VideoPlan
from render_video import _build_filter_complex, render


def _ffprobe_json(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration:stream=width,height,r_frame_rate",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def test_filter_string_shape() -> None:
    plan = VideoPlan.model_validate({
        "title": "shape",
        "aspect": "16:9", "fps": 30,
        "transition": "crossfade", "transition_duration_s": 0.5,
        "tail_hold_s": 0.0,
        "scenes": [
            {"duration_s": 2.5, "background_image": "x.png", "ken_burns": "in"},
            {"duration_s": 3.0, "background_image": "x.png", "ken_burns": "left"},
            {"duration_s": 2.5, "background_image": "x.png", "ken_burns": "out"},
        ],
    })
    fc, final = _build_filter_complex(plan)
    assert final == "[vout]"
    assert fc.count("zoompan") == 3
    assert fc.count("xfade") == 2
    assert "offset=2.0000" in fc
    assert "offset=4.5000" in fc
    assert "transition=fade" in fc
    assert "tpad" not in fc
    print("ok: filter shape")


def test_cut_mode() -> None:
    plan = VideoPlan.model_validate({
        "title": "cut", "aspect": "16:9", "fps": 30,
        "transition": "cut",
        "scenes": [
            {"duration_s": 1.0, "background_image": "x.png", "ken_burns": "none"},
            {"duration_s": 1.0, "background_image": "x.png", "ken_burns": "none"},
        ],
    })
    fc, final = _build_filter_complex(plan)
    assert "concat=n=2" in fc
    assert "xfade" not in fc
    assert final == "[vout]"
    print("ok: cut mode")


def test_single_scene() -> None:
    plan = VideoPlan.model_validate({
        "title": "single", "aspect": "9:16", "fps": 30,
        "scenes": [
            {"duration_s": 2.0, "background_image": "x.png", "ken_burns": "in"},
        ],
    })
    fc, final = _build_filter_complex(plan)
    assert final == "[v0]"
    assert "xfade" not in fc
    assert "concat" not in fc
    print("ok: single scene")


def test_validator_rejects_too_long_xfade() -> None:
    bad = {
        "title": "bad", "aspect": "16:9", "fps": 30,
        "transition": "crossfade", "transition_duration_s": 1.5,
        "tail_hold_s": 0.0,
        "scenes": [
            {"duration_s": 1.5, "background_image": "x.png"},
            {"duration_s": 2.0, "background_image": "x.png"},
        ],
    }
    try:
        VideoPlan.model_validate(bad)
    except ValueError:
        print("ok: validator rejected over-long xfade")
        return
    raise AssertionError("validator did not reject over-long xfade")


def test_render_and_ffprobe(bg_path: Path, out_path: Path) -> None:
    plan = VideoPlan.model_validate({
        "title": "render-smoke", "aspect": "16:9", "fps": 30,
        "transition": "crossfade", "transition_duration_s": 0.5,
        "tail_hold_s": 0.0,
        "scenes": [
            {"duration_s": 2.0, "background_image": str(bg_path),
             "caption": "scene one", "caption_position": "top", "ken_burns": "in"},
            {"duration_s": 2.0, "background_image": str(bg_path),
             "caption": "scene two", "caption_position": "bottom", "ken_burns": "left"},
            {"duration_s": 2.0, "background_image": str(bg_path),
             "caption": "scene three", "caption_position": "center", "ken_burns": "out"},
        ],
    })
    render(plan, out_path, bg_path.parent)
    info = _ffprobe_json(out_path)
    duration = float(info["format"]["duration"])
    expected = 6.0 - 2 * 0.5
    assert abs(duration - expected) < 0.2, (
        f"expected duration ~{expected}, got {duration}"
    )
    stream = info["streams"][0]
    assert stream["width"] == 1920 and stream["height"] == 1080
    assert stream["r_frame_rate"] == "30/1"
    print(f"ok: render-and-ffprobe (duration={duration:.3f}s, expected~{expected})")


def main() -> int:
    test_filter_string_shape()
    test_cut_mode()
    test_single_scene()
    test_validator_rejects_too_long_xfade()

    with tempfile.TemporaryDirectory(prefix="video-gen-smoke-") as tmp:
        from PIL import Image
        bg = Path(tmp) / "bg.png"
        Image.new("RGB", (1920, 1080), color=(40, 80, 120)).save(bg)
        out = Path(tmp) / "out.mp4"
        test_render_and_ffprobe(bg, out)

    print("all smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
