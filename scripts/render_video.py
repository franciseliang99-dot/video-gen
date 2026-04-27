from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _models import VideoPlan
from title_card import render_scene


def _slug(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "", title).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned or "output"


def _default_out_path(plan_title: str) -> Path:
    env = os.environ.get("VIDEO_GEN_OUT_DIR")
    if not env:
        return Path("out.mp4")
    out_dir = Path(env)
    if not out_dir.is_dir():
        print(
            f"warning: VIDEO_GEN_OUT_DIR={env} is not a directory; "
            "falling back to ./out.mp4",
            file=sys.stderr,
        )
        return Path("out.mp4")
    slug = _slug(plan_title)
    candidate = out_dir / f"{slug}.mp4"
    if candidate.exists():
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = out_dir / f"{slug}-{ts}.mp4"
    return candidate


def _resolve_asset(ref: str, plan_dir: Path) -> Path:
    p = Path(ref)
    if p.is_absolute():
        if p.exists():
            return p
        raise SystemExit(f"asset not found: {p}")
    for base in (plan_dir, Path.cwd()):
        candidate = (base / p).resolve()
        if candidate.exists():
            return candidate
    raise SystemExit(
        f"asset not found: {ref} (looked in {plan_dir} and {Path.cwd()})"
    )


def render(plan: VideoPlan, out_path: Path, plan_dir: Path) -> Path:
    res = plan.resolution
    with tempfile.TemporaryDirectory(prefix="video-gen-") as tmp:
        tmp_dir = Path(tmp)
        ffmpeg_inputs: list[str] = []
        for i, scene in enumerate(plan.scenes):
            bg_path = _resolve_asset(scene.background_image, plan_dir)
            png = tmp_dir / f"scene_{i:03d}.png"
            render_scene(
                bg_path, scene.caption, scene.caption_position, res, png,
            )
            ffmpeg_inputs += [
                "-loop", "1", "-t", f"{scene.duration_s}", "-i", str(png),
            ]

        n = len(plan.scenes)
        concat = "".join(f"[{i}:v]" for i in range(n))
        filter_complex = f"{concat}concat=n={n}:v=1:a=0,format=yuv420p[v]"

        cmd = [
            "ffmpeg", "-y", *ffmpeg_inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-r", str(plan.fps),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a VideoPlan JSON into MP4")
    ap.add_argument("plan", type=Path, help="Path to VideoPlan JSON file")
    ap.add_argument(
        "--out", type=Path, default=None,
        help=(
            "Output MP4 path. Default: $VIDEO_GEN_OUT_DIR/<title-slug>.mp4 "
            "if the env var points to an existing directory, else ./out.mp4."
        ),
    )
    args = ap.parse_args()

    plan_path: Path = args.plan.resolve()
    plan = VideoPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    out_target = args.out if args.out is not None else _default_out_path(plan.title)
    out = render(plan, out_target.resolve(), plan_path.parent)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
