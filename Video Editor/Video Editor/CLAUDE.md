# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local Python pipeline that auto-edits talking-head + screen-recording videos. It removes silences, optionally syncs and composites a phone PiP onto a screen recording, and reduces background noise. WhisperX-based filler/repeat detection and a UI layer are planned but **not yet implemented** — do not assume they exist.

## Run it

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py                    # process everything in input/
python main.py path\to\video.mp4  # process a single file
```

There is no test suite, no linter config, and no build step. Iteration is by running [main.py](main.py) on sample videos in [input/](input/) and inspecting [output/](output/).

`requirements.txt` is intentionally minimal — `noisereduce`, `scipy`, `numpy`, and `imageio-ffmpeg` are also required at runtime (the latter is pulled in transitively by `moviepy`). Keep `requirements.txt` in sync when touching deps.

## Pipelines, auto-selected by `main()`

[main.py](main.py) inspects [input/](input/) and dispatches one of:

1. **Dual-input PiP pipeline** (default when matching pairs are present). Triggered by [find_dual_inputs](main.py) detecting files named `phone.mp4` + `screen.mp4`, or numbered pairs `phone1/screen1`, `phone2/screen2`, etc. Pipeline:
   - [find_audio_offset](modules/syncer.py#L37) cross-correlates the first 60s of each track to compute drift.
   - [composite_pip](modules/syncer.py#L85) builds an FFmpeg `filter_complex` that crops the phone to a square, scales it, applies a rounded-corner alpha mask via `geq`, and overlays it on the screen recording. **Phone audio is kept; screen-recording audio is discarded.**
   - Multi-segment runs are concatenated via [concat_videos](modules/syncer.py#L164) (filter-based concat, re-encodes — not stream copy).
   - The merged output is then fed through the silence-removal pipeline below, then through audio enhancement. Both `merged_edited.mp4` and `merged_edited_enhanced.mp4` are kept side-by-side for A/B comparison.

2. **Standalone silence-removal pipeline** (fallback for any other videos in `input/`). Per file:
   - [extract_audio](modules/audio_extractor.py#L94) writes two WAVs: a 16 kHz mono `_analysis.wav` for detection, and an `_hq.wav` at original rate.
   - [detect_silences](modules/analyzer.py#L19) → [generate_cut_list](modules/analyzer.py#L60) inverts silences into keep-segments, trimming each silence inward by `keep_pause_ms / 2` on each side so cuts retain a short breath.
   - [cut_video](modules/cutter.py#L21) uses MoviePy 2.x (`subclipped`, `with_effects`, `AudioFadeIn`/`AudioFadeOut`) and applies `crossfade_ms` audio fades only on interior boundaries — never on the very first segment's fade-in or the very last segment's fade-out, to preserve real edges.

### Optional: Remotion-rendered hook (prepended)

If `input/hook.mp4` + `input/hook.json` are both present, the run renders a styled hook intro via Remotion (Node/React) and prepends it to whichever pipeline's final output produced. Detection in [find_hook_input](main.py); render via [render_hook](modules/hook_renderer.py); concat reuses [concat_videos](modules/syncer.py#L164). Outputs: `output/hook_rendered.mp4` (the standalone styled hook) and `output/.../final.mp4` (hook + main edited). Per-hook config (`hook.json`) requires `duration_seconds` and `title`; styling fields are optional and have defaults baked into [HookComposition.tsx](remotion/src/HookComposition.tsx). The CLI single-video mode (`python main.py path/to/file`) does **not** apply the hook — only batch mode (`python main.py`) does.

**Prerequisites:** Node.js installed locally and a one-time `cd remotion && npm install`. The pipeline will raise a useful error if `node_modules` is missing. The raw `hook.mp4` is staged into `remotion/public/hook_input.mp4` during render and removed after — don't rely on it being there. The hook step is gracefully skipped if render fails (logged, pipeline continues).

## FFmpeg binary discovery

Every module that shells out to FFmpeg uses the same pattern:

```python
try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"
```

The pipeline therefore works without a system-wide FFmpeg install, as long as `imageio-ffmpeg` is present. [audio_extractor.py](modules/audio_extractor.py) also locates `ffprobe.exe` next to the bundled FFmpeg. When adding a new module that calls FFmpeg, copy this block — don't hardcode `"ffmpeg"`.

## Audio enhancement is `noisereduce`, not DeepFilterNet

Despite earlier design notes, the implemented engine is spectral gating via the `noisereduce` package ([_enhance_noisereduce](modules/audio_enhancer.py#L48)). DeepFilterNet is a reserved branch that raises `NotImplementedError`. `prop_decrease` is mapped from `strength` (`light=0.6`, `default=0.85`, `strong=1.0`).

## Config

[config.json](config.json) holds all user-tunable thresholds. The actual default `silence.threshold_db` is **-55**, not -40 (the -40 value in module docstrings is the in-code fallback when `config.json` is missing). When changing defaults, update both [config.json](config.json) and the docstring fallbacks in [analyzer.py](modules/analyzer.py).

The `fillers` and `repeats` config blocks are wired into config but not yet consumed — there is no transcription/filler-detection module yet.

## Design rules to preserve

- **Never strip all silence.** Always retain `keep_pause_ms / 2` on each side of a cut. Removing this makes speech sound clipped.
- **Crossfade only at interior boundaries.** [cutter.py:69-72](modules/cutter.py#L69-L72) deliberately skips fade-in on segment 1 and fade-out on the last segment.
- **Keep both edited and enhanced outputs** in the dual-input flow — users want A/B comparison, don't auto-delete the pre-enhancement version.
- **Don't over-process noise reduction.** Stick to `default` strength unless the user explicitly asks for `strong`.

## What's not built yet (don't fabricate it)

The original design references WhisperX transcription, filler-word detection, repeated-phrase detection, SRT generation, and a Streamlit/Gradio UI. None of those exist in [modules/](modules/) today — there is no `transcriber.py`. If asked to add transcription, build it from scratch (add `whisperx` to `requirements.txt`, create the module); don't pretend a stub is there.
