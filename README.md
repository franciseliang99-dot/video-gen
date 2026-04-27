# video-gen

A Claude Code skill that turns a text prompt + a handful of images into a short MP4. **Claude is the director** (writes the scene plan, captions, timing); **ffmpeg + Pillow are the renderer**.

> Claude itself does not generate video pixels — this is a composition pipeline, not a Sora/Veo wrapper.

## Requirements

- ffmpeg 6+ on `$PATH` — `apt install ffmpeg`
- Python 3.10+ with `pydantic>=2`, `Pillow>=10`
- A CJK-capable font — `apt install fonts-noto-cjk`
- Claude Code CLI

## Install

```bash
ln -s "$(pwd)" ~/.claude/skills/video-gen
pip install --user 'pydantic>=2' 'Pillow>=10'
```

Restart Claude Code (or open a new session). The skill is auto-discovered; invoke it with `/video-gen ...`.

## Usage

```
/video-gen "Intro for a Python tutorial" --images logo.png,banner.jpg --aspect 16:9 --out intro.mp4
```

Claude will:
1. Plan ~3 scenes with captions, durations, and layout.
2. Write the plan JSON to `/tmp/`.
3. Run `scripts/render_video.py` to render.
4. Print the absolute path to the resulting MP4 and `ffprobe`-verify duration / resolution.

You can also bypass Claude and render a hand-written plan directly:

```bash
python3 scripts/render_video.py examples/sample_plan.json --out out.mp4
```

## Configuration

- `VIDEO_GEN_OUT_DIR` — if set to an existing directory, renders without an explicit `--out` go to `$VIDEO_GEN_OUT_DIR/<title-slug>.mp4`. Filename collision appends a `-YYYYMMDD-HHMMSS` suffix. Set persistently in your shell rc:
  ```bash
  echo 'export VIDEO_GEN_OUT_DIR=/home/myclaw/mnt/francise-laptop/videogened' >> ~/.bashrc
  ```

## V0.1 limits

- Image inputs only (no video clips yet)
- No audio / TTS / background music
- 1–10 scenes, total ~8–20 s
- Aspect: `16:9` or `9:16`

## V0.2 roadmap

- Video clip ingestion (`ffprobe` for metadata, scale + pad to target res, trim segments)
- Crossfade transitions between scenes
- Optional TTS narration (provider TBD — `edge-tts` is a candidate for zero-cost)

See `CHANGELOG.md`.

## Architecture

```
SKILL.md            # Claude's instructions — the director's playbook
scripts/
  _models.py        # VideoPlan / Scene pydantic models (domain)
  title_card.py     # Pillow-based per-frame compositor (background + caption)
  render_video.py   # CLI: plan JSON -> N PNG frames -> ffmpeg concat -> MP4
examples/
  sample_plan.json  # Reference VideoPlan
```

Decoupled: the renderer never talks to an LLM, the LLM never talks to ffmpeg directly. Claude reads `SKILL.md`, drafts a plan, dumps it to JSON, calls `render_video.py`. Swapping the LLM (e.g. for evals) is a single file change in `SKILL.md`; swapping the renderer is a single file change in `scripts/`.

## Authentication note

This skill runs **inside** Claude Code, inheriting the user's existing Claude Code auth. It deliberately does **not** call the Anthropic API directly via the `anthropic` SDK or read `~/.claude/.credentials.json` — that pattern is prohibited for third-party apps as of Anthropic's 2026-02 policy update. If you want a standalone CLI version of this tool, use a real `ANTHROPIC_API_KEY` from the Console.
