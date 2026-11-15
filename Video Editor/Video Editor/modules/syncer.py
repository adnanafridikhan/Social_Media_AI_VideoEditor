"""
syncer.py — Phase 1.5: Sync + Composite

Aligns a phone (talking-head) recording with a screen recording by
cross-correlating their audio waveforms, then composites the phone
video as a rounded-corner picture-in-picture overlay onto the screen
recording. Phone audio is kept; screen-recording audio is discarded.
"""

import os
import subprocess
import numpy as np
from scipy.signal import correlate
from scipy.io import wavfile

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"


def _extract_mono_wav(video_path: str, output_path: str, duration_s: float | None = None) -> str:
    """Extract a mono 16 kHz WAV from a video, optionally limited to the first N seconds."""
    cmd = [FFMPEG_BIN, "-y", "-i", video_path, "-vn",
           "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1"]
    if duration_s is not None:
        cmd += ["-t", str(duration_s)]
    cmd.append(output_path)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extract failed:\n{result.stderr.strip()}")
    return output_path


def find_audio_offset(phone_path: str, screen_path: str, work_dir: str,
                      sample_seconds: float = 60.0) -> float:
    """
    Find the time offset (in seconds) between two videos by cross-correlating
    the first `sample_seconds` of their audio tracks.

    Returns:
        offset_s: positive if the phone clip starts AFTER the screen clip
                  (i.e. trim the screen clip's first `offset_s` to align),
                  negative if the phone clip starts BEFORE the screen clip
                  (i.e. trim the phone clip's first `abs(offset_s)`).
    """
    os.makedirs(work_dir, exist_ok=True)
    phone_wav = os.path.join(work_dir, "_sync_phone.wav")
    screen_wav = os.path.join(work_dir, "_sync_screen.wav")

    print(f"[syncer] Extracting sync audio (first {sample_seconds:.0f}s)...")
    _extract_mono_wav(phone_path, phone_wav, sample_seconds)
    _extract_mono_wav(screen_path, screen_wav, sample_seconds)

    sr_p, phone = wavfile.read(phone_wav)
    sr_s, screen = wavfile.read(screen_wav)
    if sr_p != sr_s:
        raise RuntimeError(f"Sample rate mismatch: {sr_p} vs {sr_s}")

    phone = phone.astype(np.float32)
    screen = screen.astype(np.float32)
    phone -= phone.mean()
    screen -= screen.mean()
    if phone.std() > 0:
        phone /= phone.std()
    if screen.std() > 0:
        screen /= screen.std()

    print(f"[syncer] Cross-correlating {len(phone)/sr_p:.1f}s of audio...")
    corr = correlate(screen, phone, mode="full", method="fft")
    lag_samples = np.argmax(corr) - (len(phone) - 1)
    offset_s = lag_samples / sr_p

    for tmp in (phone_wav, screen_wav):
        if os.path.isfile(tmp):
            os.remove(tmp)

    print(f"[syncer] Detected offset: {offset_s:+.3f}s "
          f"({'phone starts later' if offset_s > 0 else 'phone starts earlier'})")
    return offset_s


def composite_pip(phone_path: str, screen_path: str, offset_s: float,
                  output_path: str, config: dict) -> str:
    """
    Composite phone video as a rounded-corner PiP overlay onto the screen
    recording. Uses phone audio. Aligns clips using `offset_s` from
    find_audio_offset().

    config keys (all optional):
        pip_width_pct   — PiP width as % of screen width (default 22)
        pip_position    — "bottom-left", "bottom-right", "top-left", "top-right"
                          (default "bottom-left")
        pip_padding_px  — distance from screen edge in pixels (default 30)
        corner_radius_px — rounded-corner radius (default 30)
    """
    pip_width_pct = config.get("pip_width_pct", 22)
    pip_position = config.get("pip_position", "bottom-left")
    pip_padding = config.get("pip_padding_px", 30)
    corner_radius = config.get("corner_radius_px", 30)

    if offset_s >= 0:
        screen_input_args = ["-ss", f"{offset_s:.3f}", "-i", screen_path, "-i", phone_path]
        screen_idx, phone_idx = 0, 1
    else:
        screen_input_args = ["-i", screen_path, "-ss", f"{-offset_s:.3f}", "-i", phone_path]
        screen_idx, phone_idx = 0, 1

    pos_map = {
        "bottom-left":  (f"{pip_padding}",         f"H-h-{pip_padding}"),
        "bottom-right": (f"W-w-{pip_padding}",     f"H-h-{pip_padding}"),
        "top-left":     (f"{pip_padding}",         f"{pip_padding}"),
        "top-right":    (f"W-w-{pip_padding}",     f"{pip_padding}"),
    }
    if pip_position not in pos_map:
        raise ValueError(f"Invalid pip_position: {pip_position}")
    overlay_x, overlay_y = pos_map[pip_position]

    pip_w_expr = f"iw*{pip_width_pct}/100"
    r = corner_radius

    # Filter chain:
    # 1. Phone video: center-square crop, scale to PiP width, add rounded-corner alpha mask
    # 2. Overlay onto screen recording, then trim to shortest stream
    geq_alpha = (
        f"if("
        f"gt(abs(W/2-X),W/2-{r})*gt(abs(H/2-Y),H/2-{r}),"
        f"if(lte(hypot(W/2-{r}-abs(W/2-X),H/2-{r}-abs(H/2-Y)),{r}),255,0),"
        f"255"
        f")"
    )
    filter_complex = (
        f"[{phone_idx}:v]crop='min(iw,ih)':'min(iw,ih)',"
        f"scale={pip_w_expr}:-2,"
        f"format=yuva420p,"
        f"geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='{geq_alpha}'"
        f"[pip];"
        f"[{screen_idx}:v][pip]overlay={overlay_x}:{overlay_y}:shortest=1[v]"
    )

    cmd = [FFMPEG_BIN, "-y", *screen_input_args,
           "-filter_complex", filter_complex,
           "-map", "[v]",
           "-map", f"{phone_idx}:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k",
           "-shortest",
           output_path]

    print(f"[syncer] Compositing PiP -> {output_path}")
    print(f"[syncer]   PiP: {pip_width_pct}% wide, {pip_position}, "
          f"{pip_padding}px padding, {corner_radius}px corners")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg composite failed:\n{result.stderr.strip()[-2000:]}")

    print(f"[syncer] Composite done: {output_path}")
    return output_path


def concat_videos(video_paths: list, output_path: str) -> str:
    """
    Concatenate multiple video files in order via FFmpeg's concat filter.
    Uses filter-based concat (re-encodes) so it handles minor codec/resolution
    drift between segments. All segments must have the same number of streams
    (1 video + 1 audio, which is what composite_pip produces).
    """
    if not video_paths:
        raise ValueError("concat_videos: video_paths is empty")
    if len(video_paths) == 1:
        # Trivial case — just copy
        cmd = [FFMPEG_BIN, "-y", "-i", video_paths[0], "-c", "copy", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg copy failed:\n{result.stderr.strip()}")
        return output_path

    inputs = []
    for p in video_paths:
        inputs += ["-i", p]

    n = len(video_paths)
    streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
    filter_complex = f"{streams}concat=n={n}:v=1:a=1[v][a]"

    cmd = [FFMPEG_BIN, "-y", *inputs,
           "-filter_complex", filter_complex,
           "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k",
           output_path]

    print(f"[syncer] Concatenating {n} segments -> {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed:\n{result.stderr.strip()[-2000:]}")
    print(f"[syncer] Concat done: {output_path}")
    return output_path
