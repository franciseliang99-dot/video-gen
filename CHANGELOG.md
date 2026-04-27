# Changelog

## 0.3.0 — 2026-04-27

**Narration audio support — single-pass mux**(was V0.4 work, pulled in due to director needing it; BGM remains in director).

**Added**
- `Scene.narration_path: str | None` field (pydantic) — optional per-scene audio file path (mp3 / wav / m4a — anything ffmpeg decodes).
- `render_video.py --narration s1.mp3,s2.mp3,...` CLI flag — comma list, **count must equal scene count** (else `SystemExit`).
- Resolution precedence: CLI `--narration` overrides plan's per-scene `narration_path` for **all** scenes (whole-list semantic, not per-position merge — keeps the contract simple). If plan has narration_path on **some** scenes but not all, renderer rejects (`SystemExit`).
- `_build_filter_complex(plan, n_audio)` extended:
  - When `n_audio > 0`, each narration is padded/trimmed via `aresample=async=1, apad=whole_dur=<ms>ms, atrim=duration=<s>` to the scene's **visual occupy duration** on the timeline (`d_i + tail - xd` for non-final scenes; `d_i + tail` for the final).
  - Scenes are hard-concatenated (`concat n=N v=0 a=1`) — **no audio crossfade** (V0.3). Adjacent scenes are typically different sentences in the explainer use case; hard cut is clearer.
  - Output mp4: `-c:v libx264 -c:a aac -b:a 192k`. **Not** `-shortest` (would truncate audio tail).
- `SKILL.md` updated: V0.3 capabilities + V0.3 narration timing rule (`scene.duration_s ≥ narration_actual + ~0.2s buffer`, ffprobe to measure) + render call template + verify step adds audio-stream-codec check + error handling adds narration-mismatch / narration-too-long / narration-not-found cases.

**Smoke results** — re-rendered the director's 9-scene earwax TikTok in a single `render_video.py` call: 44.20s mp4 with h264 + aac 192k, exactly matches the crossfade formula `sum(d) + N*tail - (N-1)*xd = 44.7 + 2.7 - 3.2 = 44.2s`. Director's previous two-step approach (V0.2 render + ffmpeg post-mux) was 43.90s — the 0.30s drift was encoder rounding when shortest-clipping. V0.3 single-pass is **more precise** AND **simpler downstream**.

**Backward compatible (V0.2 ↔ V0.3)** — no `--narration` AND no plan `narration_path` → renders silent video exactly like V0.2 (verified: `ffprobe` shows only video stream, duration unchanged at 43.90s).

**Why** — director was carrying narration-mux as a step-5 ffmpeg block (`ffmpeg -i video -i narration -c:v copy -c:a aac -shortest`), which (a) duplicated mp4 encoding overhead and (b) clipped video tail when narration was shorter. Moving it into video-gen single-pass eliminates both, and frees director step 5 to handle only BGM amix (which legitimately has cross-video failure-degradation logic that doesn't belong inside video-gen).

**Out of scope (V0.4)** — audio crossfade between scenes; video clip inputs.

## 0.2.5 — 2026-04-27

Out-of-band `scripts/health.py` CLI (skill itself untouched).

- New `scripts/health.py` standalone CLI: `python3 scripts/health.py --version` (plain) / `--version --json` (health JSON aligned with director maintainer protocol).
- Probes: `ffmpeg` + `ffprobe` (binary, critical), `Pillow` + `pydantic` (python, critical), Noto CJK font file (degraded if missing — Latin captions still work).
- Exit codes: `0=healthy / 1=degraded / 2=broken / 3=protocol error`.
- `VERSION` file 0.2.4 → 0.2.5 (patch bump, no skill / renderer changes).
- The skill's `allowed-tools` is **not** modified — `health.py` is invoked by director directly via Bash, not through the skill orchestration.

**Why** — director (V0.3.0+) introduced unified health-check across all 5 agents so `manifest.tool_versions` + `tool_health` are auto-populated. video-gen is a skill not a CLI; this `health.py` provides the CLI entry-point for director to query without going through the skill.

## 0.2.4 — 2026-04-26

- Caption outline thickened from a hand-rolled 3px-radius offset loop to Pillow's built-in `stroke_width=5` + `stroke_fill=(0,0,0)`. Triggered by the V0.2.3 auto-eval flagging top-positioned captions as borderline-readable on bright sky in the user's `去过的远方` render. The new stroke is consistently legible on bright/cluttered backgrounds and the code is shorter (one `draw.text(..., stroke_width=5, stroke_fill=...)` call instead of an 8-direction offset loop).

## 0.2.3 — 2026-04-26

Workflow change (`SKILL.md` only — renderer untouched).

- **Step 5: Auto-evaluate** added to `SKILL.md`. After ffprobe verification (Step 4) succeeds, Claude spawns a `general-purpose` subagent to critique the rendered video against a 4-axis rubric (caption legibility, motion, narrative arc, technical sanity) and return a `ship | minor fixes | re-render` verdict. Output format is fixed markdown so Claude can summarize.
- Verdict-driven flow: `ship` forwards critique verbatim; `minor fixes` and `re-render` summarize and **ask user** whether to apply fixes (no auto-re-render — global rule "用户意图不明 → 必须问").
- Skip conditions documented: user opt-out phrasing, raw-CLI invocation, Step 4 already failed.
- Eval failure never blocks delivery of a successfully verified video.
- Smoke test deliberately does **not** include the LLM eval — smoke must stay deterministic / offline / fast.

## 0.2.2 — 2026-04-26

Smoother scene transitions for chroma-rich content.

- **`transition_style`** (`VideoPlan.transition_style: Literal["fade","fadeblack","fadewhite","dissolve"]`, default `"fade"`) — pluggable xfade transition kind. `fadeblack` is recommended for travelogue / location-shifting plans where plain alpha blend creates a muddy mid-frame. `dissolve` (pixel-noise blend) is organic but causes caption overlap mid-transition; prefer `fadeblack`.
- **`tail_hold_s`** (`VideoPlan.tail_hold_s: float`, default 0.3, range 0–1) — clones each scene's last frame for this many seconds, giving the eye a rest-frame between Ken Burns motion and the cross-fade. Implemented via `tpad=stop_duration=…:stop_mode=clone` appended to each per-scene chain when crossfading.
- **xfade offset arithmetic updated** to account for the cloned tail: `cum += duration_s + tail_hold_s` per scene; total visible duration is now `sum(d) + N*tail_hold - (N-1)*xd` (was `sum(d) - (N-1)*xd`). Setting `tail_hold_s: 0` recovers V0.2.0 behavior.
- **Validator update**: `transition_duration_s` must be `< (shortest scene + tail_hold_s) - 0.1`.
- **Smoke test**: explicit `tail_hold_s: 0` in existing assertions to keep old expectations stable; the new `transition_style` is checked in the filter-shape test.

## 0.2.1 — 2026-04-26

- Accept any image format ffmpeg can decode (AVIF, HEIC, etc.) — not just Pillow's native JPG/PNG/WebP. New `_normalize_for_pillow` helper in `render_video.py` tries Pillow first; on `UnidentifiedImageError`/`OSError` it transcodes to PNG via `ffmpeg -i src out.png` into the per-render temp dir, then hands the PNG to Pillow for caption compositing. Zero new pip deps; ffmpeg was already required.

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
