# Video Editor — User Guide

A local Python pipeline that auto-edits talking-head and screen-recording videos: removes silences, syncs and composites a phone PiP onto a screen recording, reduces background noise, and optionally prepends a styled Remotion hook intro.

---

## 1. First-time setup

From the project root ([Video Editor/](.)):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you plan to use the hook intro feature, also install Node dependencies (one time only):

```powershell
cd remotion
npm install
cd ..
```

FFmpeg is bundled via `imageio-ffmpeg` — you do not need a system install.

---

## 2. The three ways to run it

Always activate the venv first (`.\venv\Scripts\Activate.ps1`).

### A. Single-video mode

Cuts silences out of one specific file.

```powershell
python main.py "path\to\your_video.mp4"
```

- Output goes to [output/](output/)`<filename>/<filename>_edited.mp4`.
- **The hook intro is NOT applied in this mode** — only batch mode prepends hooks.

### B. Batch mode — standalone clips

Drop any number of videos into [input/](input/) and run:

```powershell
python main.py
```

Each video is silence-cut individually. Outputs land in [output/](output/)`<video_name>/`.

### C. Batch mode — phone + screen composite (PiP)

Drop matching pairs into [input/](input/):

- **Single segment:** `phone.mp4` + `screen.mp4`
- **Multi-segment:** `phone1.mp4` + `screen1.mp4`, `phone2.mp4` + `screen2.mp4`, …

Then run:

```powershell
python main.py
```

The pipeline will:
1. Cross-correlate audio to auto-sync the two recordings.
2. Crop the phone to a rounded-corner square and overlay it on the screen recording (phone audio kept, screen audio discarded).
3. Concatenate multi-segment runs into a single `merged.mp4`.
4. Silence-cut the result.
5. Run noise reduction on the cut version.

Outputs in [output/composited/](output/composited/) and [output/merged/](output/):
- `merged.mp4` — raw composite
- `merged_edited.mp4` — after silence removal
- `merged_edited_enhanced.mp4` — after noise reduction (**both kept side-by-side for A/B comparison**)

---

## 3. Optional: Styled hook intro

If you want a Remotion-rendered hook prepended to your final video, place both files in [input/](input/):

- `hook.mp4` — the raw hook clip
- `hook.json` *(optional)* — must contain at minimum:

```json
{
  "duration_seconds": 3.0,
  "title": "Your hook title text"
}
```

The hook is silence-cut, rendered with styling from [remotion/src/HookComposition.tsx](remotion/src/HookComposition.tsx), and prepended to whichever pipeline ran. Output: `output/<name>/final.mp4`.

If only `hook.mp4` is in `input/` (no main videos), you get a **hook-only render** at `output/hook_rendered.mp4`.

Hook rendering fails gracefully — if Node/Remotion errors out, the rest of the pipeline still completes.

---

## 4. Tuning behavior — [config.json](config.json)

Edit values and re-run. Key knobs:

| Setting | What it does | Default |
|---|---|---|
| `silence.threshold_db` | Anything quieter than this counts as silence. Lower (more negative) = stricter. | `-55` |
| `silence.min_duration_ms` | Ignore silences shorter than this. | `500` |
| `silence.keep_pause_ms` | Half this much is preserved on each side of every cut — keeps speech breathing naturally. **Never set to 0.** | `250` |
| `audio_enhancement.strength` | `light` \| `default` \| `strong`. Stick to `default` unless audio is genuinely noisy. | `default` |
| `output.crossfade_ms` | Audio crossfade between cuts. Only applied to interior boundaries. | `50` |
| `composite.pip_width_pct` | Phone PiP width as % of screen width. | `22` |
| `composite.pip_position` | `bottom-left`, `bottom-right`, `top-left`, `top-right`. | `bottom-left` |
| `composite.corner_radius_px` | Rounded corner radius on the PiP. | `30` |
| `hook.enabled` | Set to `false` to disable hook prepending entirely. | `true` |

> Note: `fillers` and `repeats` blocks exist in config but are **not yet wired up** — transcription/filler detection is not implemented.

---

## 5. Outputs you can expect

For a single video `my_clip.mp4`:
```
output/my_clip/
  my_clip_edited.mp4     # silence-cut
  my_clip_report.txt     # what was removed and why
```

For a phone+screen run:
```
output/composited/
  merged.mp4             # raw composite
  final.mp4              # hook + merged_edited_enhanced (if hook present)
output/merged/
  merged_edited.mp4
  merged_edited_enhanced.mp4
```

---

## 6. Troubleshooting

- **`No videos found`** — drop files into [input/](input/) (supported: `.mp4 .mkv .avi .mov .webm .flv .wmv`).
- **`phoneN has no matching pair`** — every numbered phone needs a matching numbered screen. Unpaired files are skipped.
- **Hook render fails** — confirm `cd remotion && npm install` ran. The pipeline will continue without the hook and log the error.
- **Speech sounds clipped at cut points** — raise `silence.keep_pause_ms` in [config.json](config.json).
- **Cuts are too aggressive / not aggressive enough** — adjust `silence.threshold_db` (more negative = stricter cuts) and `silence.min_duration_ms`.
- **Enhanced audio sounds artifact-y / "underwater"** — drop `audio_enhancement.strength` to `light`, or disable it (`enabled: false`) and keep `merged_edited.mp4` instead.

---

## 7. Quick reference

```powershell
# Process everything in input/
python main.py

# Process one specific file (no hook prepend)
python main.py "C:\path\to\video.mp4"
```

Drop files into [input/](input/), get results from [output/](output/). Tune [config.json](config.json) to taste.
