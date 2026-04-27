# Changelog

## 0.1.0 — 2026-04-26

Initial scaffold. Claude-as-director pipeline.

- `VideoPlan` / `Scene` pydantic models (`scripts/_models.py`)
- `title_card.py` — Pillow per-frame compositor: scale-and-crop background image, white caption + black outline, three caption positions, Noto Sans CJK Bold via `fc-match`, automatic CJK-aware line wrapping
- `render_video.py` — CLI: VideoPlan JSON → per-scene PNGs → `ffmpeg -loop 1 -t … -filter_complex concat … -c:v libx264 -crf 20` → MP4
- `SKILL.md` — instructs Claude to plan 1–10 scenes (1.5–6 s each), pick `16:9` or `9:16` aspect, narrate-not-echo captions, save plan to `/tmp/` and shell out to `render_video.py`, verify with `ffprobe`
- `examples/sample_plan.json` — reference plan
- Authentication: skill runs inside Claude Code (option B), inheriting Claude Code's OAuth; no direct `anthropic` SDK calls — compliant with 2026-02 third-party OAuth ban
- V0.1 limits: image inputs only (video clips, TTS, BGM all out of scope)
