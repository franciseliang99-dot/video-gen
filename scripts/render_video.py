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

from PIL import Image, UnidentifiedImageError

from _models import KenBurns, VideoPlan
from title_card import render_scene


def _normalize_for_pillow(src: Path, tmp_dir: Path, idx: int) -> Path:
    try:
        with Image.open(src) as im:
            im.verify()
        return src
    except (UnidentifiedImageError, OSError):
        out = tmp_dir / f"normalized_{idx:03d}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src), str(out)],
            check=True,
        )
        return out


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


def _kb_filter(kb: KenBurns, d_frames: int, w: int, h: int, fps: int) -> str:
    if kb == "none":
        return (
            f"scale={w}:{h}:flags=lanczos,"
            f"zoompan=z=1.0:d={d_frames}:s={w}x{h}:fps={fps}"
        )

    pre = f"scale={w * 4}:{h * 4}:flags=lanczos"
    z_max = 1.15
    z_inc = (z_max - 1.0) / max(d_frames - 1, 1)
    last = max(d_frames - 1, 1)

    if kb == "in":
        z_expr = f"min(zoom+{z_inc:.6f},{z_max})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif kb == "out":
        z_expr = f"if(eq(on,0),{z_max},max(zoom-{z_inc:.6f},1.0))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif kb == "left":
        z_expr = "1.10"
        x_expr = f"(iw-iw/zoom)*(1-on/{last})"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        z_expr = "1.10"
        x_expr = f"(iw-iw/zoom)*on/{last}"
        y_expr = "ih/2-(ih/zoom/2)"

    return (
        f"{pre},"
        f"zoompan=z='{z_expr}':d={d_frames}"
        f":x='{x_expr}':y='{y_expr}':s={w}x{h}:fps={fps}"
    )


def _build_filter_complex(plan: VideoPlan) -> tuple[str, str]:
    n = len(plan.scenes)
    w, h = plan.resolution
    fps = plan.fps
    parts: list[str] = []

    use_tpad = (
        n > 1
        and plan.transition == "crossfade"
        and plan.tail_hold_s > 0
    )

    for i, sc in enumerate(plan.scenes):
        d_frames = max(1, int(round(sc.duration_s * fps)))
        kb = _kb_filter(sc.ken_burns, d_frames, w, h, fps)
        chain = f"{kb},setsar=1,format=yuv420p"
        if use_tpad:
            chain += (
                f",tpad=stop_duration={plan.tail_hold_s}:stop_mode=clone"
            )
        parts.append(f"[{i}:v]{chain}[v{i}]")

    if n == 1:
        return ";".join(parts), "[v0]"

    if plan.transition == "cut":
        concat = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{concat}concat=n={n}:v=1:a=0[vout]")
        return ";".join(parts), "[vout]"

    xd = plan.transition_duration_s
    style = plan.transition_style
    h_extra = plan.tail_hold_s if use_tpad else 0.0
    cum = 0.0
    prev = "[v0]"
    for k in range(1, n):
        cum += plan.scenes[k - 1].duration_s + h_extra
        offset = cum - k * xd
        out_label = "[vout]" if k == n - 1 else f"[x{k:02d}]"
        parts.append(
            f"{prev}[v{k}]xfade=transition={style}"
            f":duration={xd}:offset={offset:.4f}{out_label}"
        )
        prev = out_label
    return ";".join(parts), "[vout]"


def render(plan: VideoPlan, out_path: Path, plan_dir: Path) -> Path:
    w, h = plan.resolution
    with tempfile.TemporaryDirectory(prefix="video-gen-") as tmp:
        tmp_dir = Path(tmp)
        ffmpeg_inputs: list[str] = []
        for i, scene in enumerate(plan.scenes):
            bg_path = _resolve_asset(scene.background_image, plan_dir)
            bg_path = _normalize_for_pillow(bg_path, tmp_dir, i)
            png = tmp_dir / f"scene_{i:03d}.png"
            render_scene(
                bg_path, scene.caption, scene.caption_position, (w, h), png,
            )
            ffmpeg_inputs += ["-i", str(png)]

        filter_complex, final_label = _build_filter_complex(plan)
        cmd = [
            "ffmpeg", "-y", *ffmpeg_inputs,
            "-filter_complex", filter_complex,
            "-map", final_label,
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
