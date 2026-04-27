---
name: video-gen
description: Generate a short MP4 video from a text prompt + image inputs. Claude plans the scenes (caption, timing, layout); ffmpeg + Pillow render the final video. Use when the user asks to "make a video", "generate a clip", "拼一个视频" from text and images.
argument-hint: "<prompt> [--images path1,path2,...] [--aspect 16:9|9:16] [--out path]"
allowed-tools: Read Write Bash(python3 *) Bash(ls *) Bash(file *) Bash(ffprobe *)
---

# video-gen — Claude as director, ffmpeg as renderer

You orchestrate a short MP4 from user inputs. **You** plan the video; bundled scripts render it. Do not try to generate video pixels yourself — only produce a structured `VideoPlan` JSON and hand it to the renderer script.

## V0.2 capabilities

**Supported inputs**
- A text prompt describing the desired video
- 1+ static image files — any format ffmpeg can decode (jpg / png / webp / avif / heic / …)
- Aspect ratio: `16:9` (horizontal 1920×1080) or `9:16` (vertical 1080×1920). Default `16:9` if user does not specify.

**Motion** (V0.2 — defaults make single-image inputs feel alive)
- Per-scene Ken Burns zoom/pan: `in` (default subtle zoom-in), `out`, `left`, `right`, `none` (no motion).
- Plan-level transition between scenes: `crossfade` (default, 0.5s) or `cut`.

**Not supported yet** — refuse and tell user it is V0.3 work
- Video clip inputs (mp4 / mov)
- Audio narration / TTS
- Background music
- More than 10 scenes

## Pipeline

### 1. Parse the request

Extract from `$ARGUMENTS`:
- The prompt text (free-form description)
- `--images path1,path2,…` — comma-separated image paths
- `--aspect 16:9|9:16` — default `16:9`
- `--out path.mp4` — default: `$VIDEO_GEN_OUT_DIR/<title-slug>.mp4` if that env var points to an existing directory, else `./out.mp4`. If the user supplies `--out` explicitly, that wins.

Resolve every image path to absolute. Verify each file exists with `ls` before planning. If any image is missing, stop and ask the user. If the user provided **no** images, stop and ask — V0.1 cannot synthesize visuals from text alone.

### 2. Plan scenes

Produce a `VideoPlan` JSON conforming to this exact schema:

```json
{
  "title": "string",
  "aspect": "16:9",
  "fps": 30,
  "transition": "crossfade",
  "transition_style": "fade",
  "transition_duration_s": 0.5,
  "tail_hold_s": 0.3,
  "scenes": [
    {
      "duration_s": 3.0,
      "background_image": "/abs/path/to/img.png",
      "caption": "短文字 or English",
      "caption_position": "bottom",
      "ken_burns": "in"
    }
  ]
}
```

Planning rules:
- 3 scenes by default; up to 10 allowed.
- Each `duration_s` between 1.5 and 6 seconds. Total visible video ≈ `sum(duration_s) - (N-1) * transition_duration_s` for crossfade, or `sum(duration_s)` for cut.
- `transition_duration_s` must be < shortest `duration_s` minus 0.1s (validator enforces).
- `caption` short (≤ 24 CJK chars / ≤ 50 Latin chars per intended line). Renderer wraps automatically but tighter is better.
- If fewer images than scenes, cycle through them.
- Pick `caption_position` (`top` / `center` / `bottom`) so the text does not cover the salient subject. Default `bottom`.
- Captions should narrate or contextualize the prompt — not echo it verbatim. Build a small narrative arc (hook → body → close).
- `ken_burns` per scene — vary across scenes so the video has rhythm. Good defaults when single-image input: scene 1 `in`, scene 2 `left` or `right`, scene 3 `out`. For motion-rich photos, prefer `none` so detail isn't lost. Omit the field to use default `in`.
- `transition` plan-level — `crossfade` (default) for cinematic; `cut` for fast-paced or stop-motion feel. Omit to use default.
- `transition_style` (only when crossfade) — `fade` (default, plain alpha cross-blend), `fadeblack` (briefly through black, good for chroma-shifting scenes / travelogue chapter beats), `fadewhite` (through white, dreamy/airy), `dissolve` (pixel-noise blend, organic but caption-overlap during midpoint).
- `tail_hold_s` plan-level (default 0.3, range 0–1) — clones each scene's last frame for this many seconds before the crossfade kicks in. Gives the eye a "rest frame" so motion + chroma shift + blend don't all happen at once. Set 0 to recover V0.2 behavior.
- For chroma-shifting travelogue (e.g., tropical → grassland → autumn lake), prefer `transition_style: "fadeblack"` + `transition_duration_s: 1.0` + `tail_hold_s: 0.3`.

### 3. Save plan + render

Write the plan JSON to `/tmp/video-gen-plan-${CLAUDE_SESSION_ID}.json`, then run:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/render_video.py \
  /tmp/video-gen-plan-${CLAUDE_SESSION_ID}.json \
  --out <user-out-path>
```

The script prints the absolute output path on success.

### 4. Verify

Run `ffprobe -v error -show_entries format=duration:stream=width,height -of default=nw=1 <out.mp4>`. Confirm:
- `duration` ≈ sum of `duration_s` (within 0.2 s; for crossfade plans the formula is `sum(duration_s) + N*tail_hold_s - (N-1)*transition_duration_s`)
- `width × height` matches the chosen aspect (1920×1080 or 1080×1920)

If either check fails, surface the discrepancy to the user — do not silently retry.

### 5. Auto-evaluate (after Step 4 passes)

After ffprobe verification succeeds, spawn a `general-purpose` subagent to critique the rendered video. Skip this step if:
- The user said "just render", "no critique", "skip eval", or equivalent.
- The render was kicked off via raw CLI (`render_video.py` directly) without Claude in the loop.
- Step 4 already failed — fix that first.

Default: run the eval.

**Subagent prompt template** (substitute `<…>` with actual paths and values from the plan):

> You are evaluating a rendered short video. Inputs:
> - Video: `<abs out.mp4>`
> - Plan JSON: `/tmp/video-gen-plan-${CLAUDE_SESSION_ID}.json`
>
> Extract 5–6 frames with `ffmpeg -ss <t> -i <video> -vframes 1 -y /tmp/eval-frame-<i>.png`. Pick timestamps at the **middle of each scene** and the **middle of each transition** (compute from `duration_s`, `transition_duration_s`, `tail_hold_s` in the plan — do not guess).
>
> Read the frames. Score the video on this rubric. Be terse. Total response under 200 words. Use exactly this markdown skeleton:
>
> ```
> ## Caption legibility
> <1–2 sentences: visible? overlap mid-transition? covering subject?>
>
> ## Motion
> <1–2 sentences: Ken Burns direction per scene; do consecutive vectors clash?>
>
> ## Narrative arc
> <1 sentence: does the caption sequence read coherently hook→body→close?>
>
> ## Technical sanity
> <1 sentence: any visible encoding artifacts, banding, frozen frames, unexpected black flashes?>
>
> ## Verdict
> One of: `ship` | `minor fixes` | `re-render`
> If not `ship`: one concrete fix (e.g., "shorten scene 2 caption", "swap scene 3 ken_burns to `out`", "thicken caption outline for top-positioned text on bright sky").
> ```
>
> Do not invent issues to look thorough. If a section is clean, say "clean." Cleanup: `rm -rf /tmp/eval-frame-*.png` after.

**What to do with the verdict:**
- **`ship`** → forward the critique verbatim to the user under an `### Auto-eval` heading. Done.
- **`minor fixes`** → summarize the critique in 2–3 bullets, then **ask the user**: "Apply these fixes and re-render, or keep this as a draft?" Do not auto-re-render — the user may want the imperfect cut.
- **`re-render`** → surface the critique prominently, name the concrete fix the eval suggested, then ask: "Re-render with `<fix>`? Or keep current output?" Still do not auto-re-render.

**If the eval subagent itself fails** (timeout, ffmpeg error, malformed output) → tell the user "auto-eval failed: `<reason>`" and deliver the rendered video anyway. Eval failure must never block delivery of a successfully rendered + ffprobe-verified video.

## Error handling

- **Image not found** → stop, ask user for correct path. Do not fabricate a substitute.
- **ffmpeg failure** → show the last 20 lines of stderr to the user. Diagnose root cause; do not retry blindly.
- **Plan validation fails** (`pydantic.ValidationError`) → show the errors, fix the plan, regenerate. Maximum 2 attempts.
- **Non-V0.1 input** (video clip, audio file) → stop and explain it is V0.2 work.

## Examples

User: `/video-gen "Quick intro to Python" --images logo.png,banner.jpg --aspect 16:9`

You: produce a 3-scene plan such as
```json
{
  "title": "Quick intro to Python",
  "aspect": "16:9", "fps": 30,
  "scenes": [
    {"duration_s": 2.5, "background_image": "/abs/logo.png",   "caption": "Python in 10 seconds", "caption_position": "bottom"},
    {"duration_s": 3.5, "background_image": "/abs/banner.jpg", "caption": "Readable. Batteries included.", "caption_position": "center"},
    {"duration_s": 2.5, "background_image": "/abs/logo.png",   "caption": "Let's build something.", "caption_position": "bottom"}
  ]
}
```
…then render and verify.
