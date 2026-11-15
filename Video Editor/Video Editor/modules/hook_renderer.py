"""
hook_renderer.py — Hook video render via the official Remotion TikTok template

Bridges the Python pipeline to the `remotion/` Node project (cloned from
remotion-dev/template-tiktok). Given a hook clip, it:

  1. (preprocess_hook) Silence-cuts the clip using the same parameters as the
     main pipeline, so the user doesn't have to specify duration manually.
  2. (render_hook) Stages the cut clip into `remotion/public/`, runs
     Whisper.cpp via `node sub.mjs` to produce a word-timed JSON transcript,
     then runs `npx remotion render` on the CaptionedVideo composition,
     which burns animated TikTok-style captions onto the clip.

Prerequisites: Node.js installed, `npm install` run inside `remotion/`,
and Whisper.cpp installed at `remotion/whisper.cpp/` (sub.mjs handles this
on first run; on Windows the binary zip may need manual extraction if the
repo path contains spaces).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

STAGED_VIDEO_NAME = "hook_input.mp4"
STAGED_JSON_NAME = "hook_input.json"
STAGED_OVERLAYS_NAME = "overlays.json"


def _resolve_executable(name: str, win_name: Optional[str] = None) -> str:
    """Locate an executable on PATH, preferring the Windows .cmd/.exe variant."""
    candidates = []
    if win_name:
        candidates.append(win_name)
    candidates.append(name)
    for n in candidates:
        path = shutil.which(n)
        if path:
            return path
    raise RuntimeError(
        f"{name} not found on PATH. Install Node.js (https://nodejs.org)."
    )


def preprocess_hook(
    hook_video_path: str,
    output_dir: str,
    config: dict,
) -> tuple:
    """
    Silence-cut the raw hook clip. Returns (cut_video_path, duration_seconds).
    If no significant silences are detected the original clip path is returned
    unchanged.
    """
    from modules.audio_extractor import extract_audio, get_video_info
    from modules.analyzer import detect_silences, generate_cut_list
    from modules.cutter import cut_video

    info = get_video_info(hook_video_path)
    orig_duration_s = float(info.get("duration", 0) or 0)
    duration_ms = int(orig_duration_s * 1000)

    work_dir = os.path.join(output_dir, "_hook_work")
    os.makedirs(work_dir, exist_ok=True)
    audio_paths = extract_audio(hook_video_path, work_dir)

    silence_cfg = config.get("silence", {})
    silences = detect_silences(audio_paths["analysis_audio"], silence_cfg)
    keep_pause_ms = silence_cfg.get("keep_pause_ms", 250)
    keep_segments = generate_cut_list(silences, duration_ms, keep_pause_ms)

    for k in ("analysis_audio", "hq_audio"):
        p = audio_paths.get(k)
        if p and os.path.isfile(p):
            os.remove(p)
    try:
        os.rmdir(work_dir)
    except OSError:
        pass

    if not silences:
        print(f"[hook] No silences in hook clip — using original "
              f"({orig_duration_s:.2f}s)")
        return hook_video_path, orig_duration_s

    cut_path = os.path.join(output_dir, "hook_cut.mp4")
    crossfade_ms = config.get("output", {}).get("crossfade_ms", 50)
    print(f"[hook] Silence-cutting hook ({len(silences)} silence(s)) -> {cut_path}")
    cut_video(hook_video_path, keep_segments, cut_path, crossfade_ms=crossfade_ms)

    cut_info = get_video_info(cut_path)
    cut_duration_s = float(cut_info.get("duration", orig_duration_s) or orig_duration_s)
    print(f"[hook]   Cut hook duration: {cut_duration_s:.2f}s "
          f"(was {orig_duration_s:.2f}s)")
    return cut_path, cut_duration_s


def _transcribe(remotion_dir: str, staged_video_rel: str,
                node_bin: str) -> None:
    """Run sub.mjs to produce the caption JSON next to the staged video."""
    print(f"[hook] Transcribing via Whisper.cpp (this can take 30-90s)...")
    result = subprocess.run(
        [node_bin, "sub.mjs", staged_video_rel],
        cwd=remotion_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-3000:]
        raise RuntimeError(
            f"Whisper transcription failed (exit {result.returncode}):\n{tail}"
        )


def render_hook(
    hook_video_path: str,
    hook_config_path: Optional[str],
    output_path: str,
    remotion_dir: Optional[str] = None,
    duration_override: Optional[float] = None,
) -> Path:
    """
    Render a styled hook video via the official Remotion TikTok template.

    Args:
        hook_video_path: absolute path to the (already silence-cut) hook clip.
        hook_config_path: optional hook.json. Currently no per-hook fields are
                          consumed by the TikTok template; kept for forward
                          compatibility (caption styling overrides).
        output_path: where to write the rendered hook .mp4.
        remotion_dir: path to the remotion/ Node project. Defaults to
                      <repo_root>/remotion.
        duration_override: ignored. The composition derives duration from the
                           staged video's metadata via calculateMetadata.
    """
    hook_video_path = os.path.abspath(hook_video_path)
    output_path = os.path.abspath(output_path)

    if not os.path.isfile(hook_video_path):
        raise FileNotFoundError(f"Hook video not found: {hook_video_path}")

    if remotion_dir is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        remotion_dir = os.path.join(repo_root, "remotion")
    remotion_dir = os.path.abspath(remotion_dir)

    if not os.path.isdir(remotion_dir):
        raise FileNotFoundError(
            f"Remotion project not found at: {remotion_dir}."
        )
    if not os.path.isdir(os.path.join(remotion_dir, "node_modules")):
        raise RuntimeError(
            f"Remotion dependencies not installed. Run:\n"
            f"  cd {remotion_dir} && npm install"
        )
    if not os.path.isdir(os.path.join(remotion_dir, "whisper.cpp")):
        raise RuntimeError(
            f"Whisper.cpp not installed. Run:\n"
            f"  cd {remotion_dir} && node sub.mjs public/<some-video>.mp4\n"
            f"This downloads ~1.5GB on first use."
        )

    public_dir = os.path.join(remotion_dir, "public")
    os.makedirs(public_dir, exist_ok=True)
    staged_video = os.path.join(public_dir, STAGED_VIDEO_NAME)
    staged_json = os.path.join(public_dir, STAGED_JSON_NAME)
    staged_overlays = os.path.join(public_dir, STAGED_OVERLAYS_NAME)

    print(f"[hook] Staging hook -> {staged_video}")
    shutil.copyfile(hook_video_path, staged_video)
    if os.path.isfile(staged_json):
        os.remove(staged_json)

    # Stage overlays.json next to the hook clip in remotion/public/. Look for
    # input/hook_overlays.json next to the source hook video; if absent, write
    # an empty overlays file so the composition still renders cleanly.
    src_overlays = os.path.join(
        os.path.dirname(hook_video_path), "hook_overlays.json"
    )
    if os.path.isfile(src_overlays):
        print(f"[hook] Staging overlays -> {staged_overlays}")
        shutil.copyfile(src_overlays, staged_overlays)
    else:
        print(f"[hook] No hook_overlays.json found — skipping overlay layer.")
        with open(staged_overlays, "w", encoding="utf-8") as f:
            json.dump({"overlays": []}, f)

    node_bin = _resolve_executable("node", "node.exe")
    npx_bin = _resolve_executable("npx", "npx.cmd")

    _transcribe(remotion_dir, f"public/{STAGED_VIDEO_NAME}", node_bin)
    if not os.path.isfile(staged_json):
        raise RuntimeError(
            f"Transcription completed but {staged_json} was not produced."
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [
        npx_bin, "remotion", "render",
        "src/index.ts", "CaptionedVideo",
        output_path,
        "--log=info",
    ]
    print(f"[hook] Rendering captioned video -> {output_path}")
    result = subprocess.run(
        cmd,
        cwd=remotion_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )

    try:
        os.remove(staged_video)
    except OSError:
        pass

    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-3000:]
        raise RuntimeError(
            f"Remotion render failed (exit {result.returncode}):\n{tail}"
        )
    if not os.path.isfile(output_path):
        raise RuntimeError(
            f"Remotion reported success but output not found: {output_path}"
        )

    print(f"[hook] Render done: {output_path}")
    return Path(output_path)


def _probe_duration_seconds(video_path: str) -> Optional[float]:
    """Return duration in seconds via the audio_extractor probe, or None."""
    try:
        from modules.audio_extractor import get_video_info
        info = get_video_info(video_path)
        d = info.get("duration")
        return float(d) if d is not None else None
    except Exception:
        return None
