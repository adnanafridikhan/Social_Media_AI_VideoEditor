"""
audio_enhancer.py — Phase 2 (lite): Audio Enhancement

Reduces background noise on a video's audio track and writes a new
video file with the enhanced audio muxed back in. Currently supports
the `noisereduce` engine (spectral gating); a `deepfilternet` engine
slot is reserved for later upgrade.
"""

import os
import subprocess
import numpy as np
from scipy.io import wavfile

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"


def _extract_audio_wav(video_path: str, output_wav: str) -> str:
    """Extract audio from a video to a stereo PCM WAV at original sample rate."""
    cmd = [FFMPEG_BIN, "-y", "-i", video_path, "-vn",
           "-acodec", "pcm_s16le", output_wav]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extract failed:\n{result.stderr.strip()}")
    return output_wav


def _mux_audio_into_video(video_path: str, audio_path: str, output_path: str) -> str:
    """Replace a video's audio track with `audio_path` (video stream copied, audio re-encoded to AAC)."""
    cmd = [FFMPEG_BIN, "-y",
           "-i", video_path,
           "-i", audio_path,
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k",
           "-shortest",
           output_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg mux failed:\n{result.stderr.strip()}")
    return output_path


def _enhance_noisereduce(input_wav: str, output_wav: str, strength: str) -> None:
    """Apply spectral-gating noise reduction via the noisereduce package."""
    import noisereduce as nr

    sr, data = wavfile.read(input_wav)
    orig_dtype = data.dtype

    is_stereo = data.ndim == 2
    audio = data.astype(np.float32)
    if is_stereo:
        audio = audio.T  # noisereduce expects (channels, samples)

    prop_decrease = {"light": 0.6, "default": 0.85, "strong": 1.0}.get(strength, 0.85)

    print(f"[audio_enhancer] Reducing noise (engine=noisereduce, strength={strength}, "
          f"prop_decrease={prop_decrease})...")
    reduced = nr.reduce_noise(y=audio, sr=sr, stationary=False, prop_decrease=prop_decrease)

    if is_stereo:
        reduced = reduced.T

    if np.issubdtype(orig_dtype, np.integer):
        info = np.iinfo(orig_dtype)
        reduced = np.clip(reduced, info.min, info.max).astype(orig_dtype)
    else:
        reduced = reduced.astype(orig_dtype)

    wavfile.write(output_wav, sr, reduced)


def enhance_video_audio(video_path: str, output_path: str, config: dict) -> str:
    """
    Run noise reduction on the audio of `video_path` and write the result
    (video stream copied, enhanced audio muxed in) to `output_path`.

    config keys:
        engine    — "noisereduce" (default). Reserved: "deepfilternet".
        strength  — "light" | "default" | "strong" (default "default").

    Returns:
        output_path on success.
    """
    engine = config.get("engine", "noisereduce")
    strength = config.get("strength", "default")

    work_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(work_dir, exist_ok=True)

    raw_wav = os.path.join(work_dir, "_enhance_raw.wav")
    clean_wav = os.path.join(work_dir, "_enhance_clean.wav")

    print(f"[audio_enhancer] Extracting audio for enhancement...")
    _extract_audio_wav(video_path, raw_wav)

    if engine == "noisereduce":
        _enhance_noisereduce(raw_wav, clean_wav, strength)
    elif engine == "deepfilternet":
        raise NotImplementedError(
            "DeepFilterNet engine is not yet wired up. "
            "Install with: pip install deepfilternet  "
            "(adds ~2.5 GB of PyTorch deps)."
        )
    else:
        raise ValueError(f"Unknown audio_enhancement engine: {engine}")

    print(f"[audio_enhancer] Muxing enhanced audio back into video...")
    _mux_audio_into_video(video_path, clean_wav, output_path)

    for tmp in (raw_wav, clean_wav):
        if os.path.isfile(tmp):
            os.remove(tmp)

    print(f"[audio_enhancer] Enhanced video: {output_path}")
    return output_path
