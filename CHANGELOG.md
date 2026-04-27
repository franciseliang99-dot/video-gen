# Changelog

## 0.2.0 — 2026-04-26

Motion: single-image inputs are no longer static.

- **Ken Burns per scene** — `Scene.ken_burns: Literal["none","in","out","left","right"]`, default `"in"`. Implemented via ffmpeg `zoompan` filter with 4× lanczos pre-scale (avoids the well-known integer-rounding stair-step artifact).
- **Crossfade between scenes** — `VideoPlan.transition: Literal["cut","crossfade"]` (default `"crossfade"`) and `transition_duration_s: float` (default 0.5, range 0.1–2.0). Implemented via chained `xfade=fade:offset=…` filters.
- **Filter graph builder extracted** — new `_build_filter_complex(plan) -> (filter_str, final_label)` in `render_video.py`; unit-testable without invoking ffmpeg.
- **Validator**: `transition_duration_s` must be less than the shortest `duration_s` minus 0.1s.
- **Smoke test** — `scripts/smoke_test.py` covers filter-string shape, cut mode, single-scene, validator rejection, and an end-to-end render + ffprobe duration check.
- **Pipeline change** — per-scene ffmpeg input is now a single PNG frame (no `-loop 1 -t`); zoompan controls the per-scene output frame count. Old `-loop 1 -t` + concat would feed multi-frame input into zoompan and inflate output duration ~20×.
- **Backwards compatibility** — V0.1 plans still parse and render; defaults yield a livelier output (mild zoom-in + crossfade) instead of the prior hard-cut static frames. To get V0.1's behavior, set `ken_burns: "none"` on every scene and `transition: "cut"`.
- **Total visible duration** changes for crossfade plans: `sum(duration_s) - (N-1) * transition_duration_s` (was `sum(duration_s)` in V0.1).

## 0.1.1 — 2026-04-26

- `render_video.py`: `--out` now defaults to `$VIDEO_GEN_OUT_DIR/<title-slug>.mp4` when the env var points to an existing directory; collision adds a `-YYYYMMDD-HHMMSS` suffix. Falls back to `./out.mp4` if the env var is unset; warns to stderr if it is set but the dir is missing. Explicit `--out` still wins.
- Slug strips path-unsafe chars (`\/:*?"<>|`), collapses whitespace to `-`, keeps CJK; falls back to `output` if the title sanitizes to empty.

## 0.1.0 — 2026-04-26

Initial scaffold. Claude-as-director pipeline.

- `VideoPlan` / `Scene` pydantic models (`scripts/_models.py`)
- `title_card.py` — Pillow per-frame compositor: scale-and-crop background image, white caption + black outline, three caption positions, Noto Sans CJK Bold via `fc-match`, automatic CJK-aware line wrapping
- `render_video.py` — CLI: VideoPlan JSON → per-scene PNGs → `ffmpeg -loop 1 -t … -filter_complex concat … -c:v libx264 -crf 20` → MP4
- `SKILL.md` — instructs Claude to plan 1–10 scenes (1.5–6 s each), pick `16:9` or `9:16` aspect, narrate-not-echo captions, save plan to `/tmp/` and shell out to `render_video.py`, verify with `ffprobe`
- `examples/sample_plan.json` — reference plan
- Authentication: skill runs inside Claude Code (option B), inheriting Claude Code's OAuth; no direct `anthropic` SDK calls — compliant with 2026-02 third-party OAuth ban
- V0.1 limits: image inputs only (video clips, TTS, BGM all out of scope)
