---
name: video-gen
description: Generate a short MP4 video from a text prompt + image inputs. Claude plans the scenes (caption, timing, layout); ffmpeg + Pillow render the final video. Use when the user asks to "make a video", "generate a clip", "拼一个视频" from text and images.
argument-hint: "<prompt> [--images path1,path2,...] [--aspect 16:9|9:16] [--out path]"
allowed-tools: Read Write Bash(python3 *) Bash(ls *) Bash(file *) Bash(ffprobe *)
---

# video-gen — Claude as director, ffmpeg as renderer

You orchestrate a short MP4 from user inputs. **You** plan the video; bundled scripts render it. Do not try to generate video pixels yourself — only produce a structured `VideoPlan` JSON and hand it to the renderer script.

## V0.1 capabilities

**Supported inputs**
- A text prompt describing the desired video
- 1+ static image files (jpg / png / webp)
- Aspect ratio: `16:9` (horizontal 1920×1080) or `9:16` (vertical 1080×1920). Default `16:9` if user does not specify.

**Not supported in V0.1** — refuse and tell the user it is V0.2 work
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
  "scenes": [
    {
      "duration_s": 3.0,
      "background_image": "/abs/path/to/img.png",
      "caption": "短文字 or English",
      "caption_position": "bottom"
    }
  ]
}
```

Planning rules:
- 3 scenes by default; up to 10 allowed.
- Each `duration_s` between 1.5 and 6 seconds. Total video roughly 8–20 s.
- `caption` short (≤ 24 CJK chars / ≤ 50 Latin chars per intended line). Renderer wraps automatically but tighter is better.
- If fewer images than scenes, cycle through them.
- Pick `caption_position` (`top` / `center` / `bottom`) so the text does not cover the salient subject. Default `bottom`.
- Captions should narrate or contextualize the prompt — not echo it verbatim. Build a small narrative arc (hook → body → close).

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
- `duration` ≈ sum of `duration_s` (within 0.2 s)
- `width × height` matches the chosen aspect (1920×1080 or 1080×1920)

If either check fails, surface the discrepancy to the user — do not silently retry.

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
