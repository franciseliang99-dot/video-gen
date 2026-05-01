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


def _build_filter_complex(plan: VideoPlan, n_audio: int = 0) -> tuple[str, str, str | None]:
    """Returns (filter_complex_str, video_out_label, audio_out_label_or_None).

    n_audio: number of narration audio inputs appended after the n_scenes video inputs.
    If n_audio > 0, audio_out_label is built as '[aout]'; else None.
    """
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
        v_out = "[v0]"
    elif plan.transition == "cut":
        concat = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{concat}concat=n={n}:v=1:a=0[vout]")
        v_out = "[vout]"
    else:
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
        v_out = "[vout]"

    # Audio chain (V0.3): each narration audio is padded/trimmed to the scene's
    # exact "occupy" duration on the final timeline, then hard-concatenated.
    # Math: scenes 0..n-2 occupy `d_i + tail - xd` each (xfade overlap is shared
    # with the next scene); scene n-1 occupies `d_{n-1} + tail`.
    a_out: str | None = None
    if n_audio > 0:
        if n_audio != n:
            raise SystemExit(
                f"narration count mismatch: got {n_audio} audio inputs but plan has {n} scenes"
            )
        tail = plan.tail_hold_s if use_tpad else 0.0
        xd = plan.transition_duration_s if (plan.transition == "crossfade" and n > 1) else 0.0
        for i, sc in enumerate(plan.scenes):
            occupy = sc.duration_s + tail - (xd if i < n - 1 else 0.0)
            occupy_ms = max(int(round(occupy * 1000)), 1)
            audio_in = i + n  # ffmpeg input index for narration_i
            # apad whole_dur ensures silence pad if audio shorter; atrim caps if longer.
            parts.append(
                f"[{audio_in}:a]aresample=async=1,"
                f"apad=whole_dur={occupy_ms}ms,"
                f"atrim=duration={occupy:.4f}[a{i}]"
            )
        concat_audio = "".join(f"[a{i}]" for i in range(n))
        # V0.3.3 (refs #2): single-pass loudnorm to TikTok / Shorts target.
        # Inlined into filter_complex (NOT -af) because ffmpeg rejects mixing
        # simple and complex filtering on the same stream:
        #   "Simple and complex filtering cannot be used together for the same stream."
        # print_format=summary lets render() parse Input LRA after the run for
        # high-dynamic-range warnings (the toothbrush LRA=18.20 case from issue #2).
        parts.append(
            f"{concat_audio}concat=n={n}:v=0:a=1,"
            f"loudnorm=I=-14:LRA=11:TP=-1:print_format=summary[aout]"
        )
        a_out = "[aout]"

    return ";".join(parts), v_out, a_out


def render(
    plan: VideoPlan,
    out_path: Path,
    plan_dir: Path,
    narration_paths: list[Path] | None = None,
) -> Path:
    """Render plan to MP4. If narration_paths is non-empty, mux as AAC audio track."""
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

        n_audio = 0
        if narration_paths:
            for ap in narration_paths:
                ffmpeg_inputs += ["-i", str(ap)]
            n_audio = len(narration_paths)

        filter_complex, v_label, a_label = _build_filter_complex(plan, n_audio)
        cmd = [
            "ffmpeg", "-y", *ffmpeg_inputs,
            "-filter_complex", filter_complex,
            "-map", v_label,
        ]
        if a_label:
            # loudnorm is inlined into filter_complex above (see _build_filter_complex);
            # we only need to map+encode here.
            cmd += ["-map", a_label, "-c:a", "aac", "-b:a", "192k"]
        cmd += [
            "-r", str(plan.fps),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        if a_label:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            sys.stderr.write(result.stderr)
            m = re.search(r"Input LRA:\s+(-?[\d.]+)\s*LU", result.stderr)
            if m and float(m.group(1)) > 15.0:
                print(
                    f"warning: input LRA {float(m.group(1)):.2f} LU exceeds 15; "
                    "single-pass loudnorm may leave residual segment-level "
                    "imbalance (e.g. silent narration vs loud BGM interleaving) — "
                    "consider per-segment leveling upstream",
                    file=sys.stderr,
                )
        else:
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
    ap.add_argument(
        "--narration", default=None,
        help=(
            "Comma-separated list of audio files (one per scene, in order). "
            "Length must equal number of scenes. Each is padded/trimmed to the "
            "scene's visual duration; output mp4 has h264+aac. "
            "If omitted, plan's per-scene narration_path fields are used; if those "
            "are also empty, output mp4 has no audio track (V0.2 behavior)."
        ),
    )
    args = ap.parse_args()

    plan_path: Path = args.plan.resolve()
    plan = VideoPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    out_target = args.out if args.out is not None else _default_out_path(plan.title)

    # Resolve narration sources: CLI > plan field. CLI list overrides ALL plan fields.
    narration_paths: list[Path] = []
    if args.narration:
        cli_list = [s.strip() for s in args.narration.split(",") if s.strip()]
        if len(cli_list) != len(plan.scenes):
            raise SystemExit(
                f"--narration count {len(cli_list)} != scenes {len(plan.scenes)}"
            )
        narration_paths = [_resolve_asset(p, plan_path.parent) for p in cli_list]
    elif any(sc.narration_path for sc in plan.scenes):
        if not all(sc.narration_path for sc in plan.scenes):
            raise SystemExit(
                "plan has narration_path on some scenes but not all; "
                "either set on every scene or pass --narration explicitly"
            )
        narration_paths = [
            _resolve_asset(sc.narration_path, plan_path.parent) for sc in plan.scenes
        ]
    # else: narration_paths stays empty → V0.2 silent-video behavior

    out = render(plan, out_target.resolve(), plan_path.parent, narration_paths or None)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
