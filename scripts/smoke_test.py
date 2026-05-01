from __future__ import annotations

import json
import re
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
    fc, final, _ = _build_filter_complex(plan)
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
    fc, final, _ = _build_filter_complex(plan)
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
    fc, final, _ = _build_filter_complex(plan)
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


def test_loudnorm_integration(bg_path: Path, out_path: Path) -> None:
    """V0.3.3+ (refs #2): rendered output integrated loudness must land near -14 LUFS.

    Generates three quiet sine narrations (~ -30 dBFS) so loudnorm has to *boost* —
    matches the realistic edge-tts edge case where input is far below the target.
    """
    plan_dir = bg_path.parent
    narration_paths: list[Path] = []
    for i, (freq, dur) in enumerate([(440.0, 1.5), (523.25, 2.0), (659.25, 1.5)]):
        ap = plan_dir / f"narr_{i}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi",
             "-i", f"sine=frequency={freq}:duration={dur}:sample_rate=44100",
             "-af", "volume=-30dB",
             str(ap)],
            check=True,
        )
        narration_paths.append(ap)

    plan = VideoPlan.model_validate({
        "title": "loudnorm-smoke", "aspect": "16:9", "fps": 30,
        "transition": "crossfade", "transition_duration_s": 0.5,
        "tail_hold_s": 0.0,
        "scenes": [
            {"duration_s": 2.0, "background_image": str(bg_path), "ken_burns": "in"},
            {"duration_s": 2.5, "background_image": str(bg_path), "ken_burns": "left"},
            {"duration_s": 2.0, "background_image": str(bg_path), "ken_burns": "out"},
        ],
    })
    render(plan, out_path, plan_dir, narration_paths)

    # Re-measure: loudnorm in analysis mode reports input_i = file's actual LUFS.
    # Use I=-14 here so that if loudnorm during render worked, output_i is also
    # near -14 (idempotent re-application).
    measure = subprocess.run(
        ["ffmpeg", "-i", str(out_path),
         "-af", "loudnorm=I=-14:LRA=11:TP=-1:print_format=json",
         "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    )
    m = re.search(r'"input_i"\s*:\s*"(-?[\d.]+)"', measure.stderr)
    assert m, (
        f"could not parse input_i from ffmpeg analysis output; tail:\n"
        f"{measure.stderr[-1500:]}"
    )
    measured = float(m.group(1))
    assert -15.0 <= measured <= -13.0, (
        f"output integrated loudness {measured:.2f} LUFS not in [-15, -13] band; "
        "loudnorm during render is not landing on target"
    )
    print(f"ok: loudnorm-integration (input_i={measured:.2f} LUFS, target -14)")


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

        out_audio = Path(tmp) / "out_audio.mp4"
        test_loudnorm_integration(bg, out_audio)

    print("all smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
