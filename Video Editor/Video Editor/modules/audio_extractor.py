"""
audio_extractor.py

Extracts audio from video files using FFmpeg via subprocess.
Part of the AI video editing pipeline — Phase 1: silence remover.
"""

import os
import json
import subprocess

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
    # ffprobe sits next to ffmpeg in the same directory
    _ffprobe_path = os.path.join(os.path.dirname(FFMPEG_BIN), "ffprobe.exe")
    FFPROBE_BIN = _ffprobe_path if os.path.isfile(_ffprobe_path) else "ffprobe"
except ImportError:
    FFMPEG_BIN = "ffmpeg"
    FFPROBE_BIN = "ffprobe"


def get_video_info(video_path: str) -> dict:
    """
    Uses FFmpeg to retrieve metadata about a video file by parsing stderr output.

    Returns a dict with keys:
        duration      - total duration in seconds (float)
        width         - video width in pixels (int)
        height        - video height in pixels (int)
        fps           - frames per second (float)
        audio_sample_rate - audio sample rate in Hz (int)

    Raises RuntimeError if FFmpeg is not found or the file cannot be read.
    """
    import re

    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cmd = [FFMPEG_BIN, "-i", video_path, "-hide_banner"]

    print(f"[audio_extractor] Probing video: {video_path}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            "FFmpeg not found. Make sure FFmpeg is installed and available on PATH."
        )

    # ffmpeg -i exits with code 1 when no output is specified, but still
    # prints metadata to stderr — that's expected.
    output = result.stderr

    info = {
        "duration": None,
        "width": None,
        "height": None,
        "fps": None,
        "audio_sample_rate": None,
    }

    # Parse duration: "Duration: 00:05:23.45"
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", output)
    if dur_match:
        h, m, s, frac = dur_match.groups()
        info["duration"] = int(h) * 3600 + int(m) * 60 + int(s) + int(frac) / (10 ** len(frac))

    # Parse video stream: "Stream #0:0: Video: h264 ..., 1920x1080 ..., 30 fps"
    vid_match = re.search(r"Stream.*Video:.*?(\d{2,5})x(\d{2,5})", output)
    if vid_match:
        info["width"] = int(vid_match.group(1))
        info["height"] = int(vid_match.group(2))

    # Parse fps: "29.97 fps" or "30 fps" or "25 tbr"
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:fps|tbr)", output)
    if fps_match:
        info["fps"] = float(fps_match.group(1))

    # Parse audio sample rate: "44100 Hz" or "48000 Hz"
    audio_match = re.search(r"(\d+)\s*Hz", output)
    if audio_match:
        info["audio_sample_rate"] = int(audio_match.group(1))

    print(
        f"[audio_extractor] Info — duration={info['duration']}s  "
        f"resolution={info['width']}x{info['height']}  fps={info['fps']}  "
        f"audio_sample_rate={info['audio_sample_rate']}Hz"
    )
    return info


def extract_audio(video_path: str, output_dir: str) -> dict:
    """
    Extracts two audio tracks from a video file using FFmpeg:

      1. analysis_audio — 16-bit PCM WAV, mono, 16 kHz
         Intended for silence detection / speech analysis.

      2. hq_audio      — 16-bit PCM WAV, original sample rate, stereo if available
         Intended for use in the final re-assembled output.

    Args:
        video_path:  Absolute or relative path to the source video file.
        output_dir:  Directory where the extracted WAV files will be written.
                     Created automatically if it does not exist.

    Returns:
        {
            "analysis_audio": "<output_dir>/<stem>_analysis.wav",
            "hq_audio":       "<output_dir>/<stem>_hq.wav",
        }

    Raises:
        FileNotFoundError — video file does not exist.
        RuntimeError      — FFmpeg not found, or extraction fails.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    os.makedirs(output_dir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(video_path))[0]
    analysis_path = os.path.join(output_dir, f"{stem}_analysis.wav")
    hq_path = os.path.join(output_dir, f"{stem}_hq.wav")

    # -- Analysis audio (mono, 16 kHz, 16-bit PCM) ---------------------------
    print(f"[audio_extractor] Extracting analysis audio -> {analysis_path}")

    cmd_analysis = [
        FFMPEG_BIN,
        "-y",                      # overwrite without asking
        "-i", video_path,
        "-vn",                     # drop video stream
        "-acodec", "pcm_s16le",    # 16-bit PCM little-endian
        "-ar", "16000",            # 16 kHz sample rate
        "-ac", "1",                # mono
        analysis_path,
    ]

    try:
        result = subprocess.run(cmd_analysis, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            "FFmpeg not found. Make sure FFmpeg is installed and available on PATH."
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed while extracting analysis audio "
            f"(exit {result.returncode}):\n{result.stderr.strip()}"
        )

    print(f"[audio_extractor] Analysis audio done: {analysis_path}")

    # -- High-quality audio (stereo preserved, original sample rate) ----------
    print(f"[audio_extractor] Extracting high-quality audio -> {hq_path}")

    cmd_hq = [
        FFMPEG_BIN,
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",    # uncompressed PCM for lossless copy
        # No -ar or -ac flags — let FFmpeg preserve original values
        hq_path,
    ]

    try:
        result = subprocess.run(cmd_hq, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            "FFmpeg not found. Make sure FFmpeg is installed and available on PATH."
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed while extracting high-quality audio "
            f"(exit {result.returncode}):\n{result.stderr.strip()}"
        )

    print(f"[audio_extractor] High-quality audio done: {hq_path}")

    return {
        "analysis_audio": analysis_path,
        "hq_audio": hq_path,
    }


# ---------------------------------------------------------------------------
# Quick smoke-test (run this file directly to verify FFmpeg is accessible)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python audio_extractor.py <video_file> [output_dir]")
        sys.exit(1)

    video = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(video), "audio_output"
    )

    try:
        info = get_video_info(video)
        print("\nVideo info:", json.dumps(info, indent=2))

        paths = extract_audio(video, out_dir)
        print("\nExtracted audio files:")
        for key, path in paths.items():
            print(f"  {key}: {path}")
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
