# Changelog

## 0.3.2 — 2026-04-30

**Caption wrap fix** — `_wrap_caption()` no longer breaks Latin words mid-letter (refs #1).

**Bug** (5/5 director-pipeline outputs reproduced in issue body):
- `STOP. You're doin\ng it wrong.` (broken: `doing`)
- `Faster than a .22 b\nullet` (broken: `bullet`)
- `1500 N - 2500x bo\ndy weight` (broken: `body`)
- `The commute is h\ners` (broken: `hers`)
- `Step 4: Backs of ha\nds` (broken: `hands`)

**Root cause**: `scripts/title_card.py:_wrap_caption` accumulated one *char* at a time and broke whenever the trial bbox exceeded `max_width`, with zero whitespace lookahead. Worked for CJK (no spaces) but mangled every Latin caption that needed wrapping.

**Fix**: word-level greedy fill via `text.split(" ")`. Tokens longer than `max_width` (CJK strings as one big token, or pathological ASCII like `supercalifragilistic...`) fall back to per-character wrapping — so CJK behavior is *byte-for-byte unchanged* (verified by `test_cjk_char_split_preserved`). Explicit `\n` continues to force a break.

**Tests** — new `tests/test_wrap.py` (project's first proper test directory; `scripts/smoke_test.py` stays focused on render/ffprobe integration):
- `test_latin_no_mid_word_break` — all 5 issue captions assert no fragment exists outside the original token set
- `test_cjk_char_split_preserved` — `牙齿王国`, `把光留在水面` round-trip char-perfect
- `test_explicit_newline_creates_break` — `Line1\nLine2` → `["Line1", "Line2"]`
- `test_oversized_token_falls_back_to_char_split` — 34-char Latin word in 200px column wraps without char loss
- `test_short_caption_single_line`, `test_empty_input_returns_empty` — boundary

**Drive-by fix** — `scripts/smoke_test.py` had been broken since V0.3.0: three `fc, final = _build_filter_complex(plan)` sites unpacked 2 values from a function that returned 3-tuple `(filter, v_label, a_label)`. Updated to `fc, final, _ = _build_filter_complex(plan)`. Acceptance criterion "smoke test passes" was unreachable without this; flagged here rather than buried in a separate commit because it's load-bearing for issue #2's verification too.

**Backwards compat** — Captions that previously rendered correctly (CJK, short Latin that fit on one line, captions that happened to break on a space-bordering character) all render bit-identically. The fix is purely additive on the wrap-overflow path.

## 0.3.1 — 2026-04-27

**Doc-truth fix** — `tail_hold_s` Field range tightened from `0.0-1.0` (V0.2.x advertised) to `0.0-0.3` (empirically safe upper bound). SKILL.md updated to match. Surfaced by director's tokyo-editor pipeline using `tail_hold_s=1.0` and getting a 6.07s video stream instead of 59.8s.

**Boundary** (measured this release, ffmpeg 6.x, single-image-per-scene, 9-scene 9:16 plan):
- `tail_hold_s ≤ 0.3` → video duration matches formula `sum(d) + N*tail - (N-1)*xd` ✓
- `tail_hold_s ≥ 0.4` → video stream plateaus at ~6s regardless of plan total; ffmpeg log shows `frame=129 ... drop=1700+`, classic filter-graph downstream-doesn't-consume / upstream-keeps-supplying deadlock.

**Root cause** (Plan subagent diagnosed, confirmed by ffmpeg log inspection):
- Each png input is a single-frame stream → EOFs after 1 frame.
- `zoompan d=180` emits the per-scene 30fps×6s=180 frames from that one input frame.
- `tpad=stop_duration=N:stop_mode=clone` then needs to clone the *zoompan output's last frame* for another `N*30` frames.
- ffmpeg's internal frame-queue between filters appears bounded ~9 frames in this configuration. `tail_hold_s=0.3` → `0.3·30=9` clone frames just fits; `tail_hold_s ≥ 0.4` → `≥12` clone frames → overflow → deadlock.

**Failed fix attempt (kept in branch history,  reverted before V0.3.1 cut)**: added `-loop 1 -t (scene.duration_s + tail_hold_s + 0.5)` per png input, hoping looped input would prevent tpad starvation. Plan subagent claimed `zoompan d=` would hard-cap output frame count. **Empirical reality**: zoompan `d=` is *per-input-frame* (each input frame produces `d` output frames), so a 7.5s loop at 30fps = 225 input frames → 225·180 = 40500 output frames per scene. Total tokyo 9-scene rendered to **1180.8s** with 35424 frames (42 MB) — exactly the V0.2.0 → V0.2.1 anti-pattern that history already warned about. Reverted, switched to truth-in-doc fix instead.

**Other fixes attempted and rejected**:
- `-thread_queue_size 4096` per input: no effect (the deadlock is inside filter-graph, not at input demuxer thread).
- `loop` filter post-zoompan: would cache all frames in RAM (700+ MB for 9-scene 4K-internal pipeline), risky on small boxes; deferred.

**Why this is the right fix despite being "just clamping the range"**:
1. The `0.0-1.0` range was wishful from V0.2.x — only the default `0.3` was ever empirically validated (earwax video V0.2 ran at 0.3 for 43.9s OK).
2. SKILL.md now matches reality, callers can plan against truth.
3. The deeper ffmpeg fix (custom filter or framequeue knob) is non-portable across ffmpeg builds and would re-introduce machine-specific surprises.
4. If a caller really needs longer tail (cinematic chapter beats), they can use `transition_style: "fadeblack"` + `transition_duration_s: 1.0` instead — already documented as the correct pattern for chroma-shifting beats.

**Backwards compat**: V0.2 silent plans, V0.3 narration plans, plans with `tail_hold_s ≤ 0.3` all unaffected. Plans with `tail_hold_s > 0.3` now fail at pydantic validation with a clear error (was previously rendering a broken 6s clip silently — strict failure preferred).

**Lesson into director maintainer.md §6.7** (待 director V0.4.2): **subagent ffmpeg / system-behavior推理实施前必须 single-step smoke verify root cause**. Plan subagent diagnosed framequeue overflow + recommended `-loop 1 -t`. Diagnosis was right (root cause = framequeue deadlock), but recommended fix conflicted with zoompan's per-input-frame multiplication semantics. A 30-second mock-run before full implementation would have caught it. This pattern parallels §6.1 (实测优先于推理 picture-gen 误判) — same lesson, different surface.

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
