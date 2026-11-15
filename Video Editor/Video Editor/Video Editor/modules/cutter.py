"""
cutter.py - Video cutting and stitching module for the AI video editing pipeline.

Phase 1: Silence Remover
Cuts video segments and concatenates them with optional audio crossfades
to avoid pops at cut points.
"""

import os
import subprocess
from moviepy import VideoFileClip, concatenate_videoclips
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"


def cut_video(
    video_path: str,
    keep_segments: list,
    output_path: str,
    crossfade_ms: int = 50,
) -> str:
    """
    Extract and concatenate video segments, with tiny audio crossfades at cut points.

    Args:
        video_path:     Path to the source video file.
        keep_segments:  List of dicts [{"start_ms": int, "end_ms": int}, ...]
                        defining the time ranges to keep (in milliseconds).
        output_path:    Destination path for the rendered output video.
        crossfade_ms:   Duration of audio fade-in / fade-out applied at each
                        cut boundary to prevent audio pops (default 50 ms).

    Returns:
        output_path on success.

    Raises:
        ValueError: If keep_segments is empty or malformed.
    """
    if not keep_segments:
        raise ValueError("keep_segments is empty — nothing to cut.")

    crossfade_s = crossfade_ms / 1000.0
    total = len(keep_segments)

    source = VideoFileClip(video_path)
    subclips = []

    try:
        for idx, seg in enumerate(keep_segments, start=1):
            print(f"Cutting segment {idx}/{total}...")

            start_s = seg["start_ms"] / 1000.0
            end_s = seg["end_ms"] / 1000.0

            # Clamp to source duration so we never overshoot
            end_s = min(end_s, source.duration)

            clip = source.subclipped(start_s, end_s)

            # Apply tiny audio crossfades to smooth cut boundaries.
            # Only add fade-in on segments after the first, and fade-out on
            # segments before the last, so we don't silence the real edges.
            if clip.audio is not None:
                if idx > 1:
                    clip = clip.with_effects([AudioFadeIn(crossfade_s)])
                if idx < total:
                    clip = clip.with_effects([AudioFadeOut(crossfade_s)])

            subclips.append(clip)

        print(f"Concatenating {total} segment(s)...")
        final = concatenate_videoclips(subclips, method="compose")

        print(f"Writing output to: {output_path}")
        final.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            logger="bar",
        )

        final.close()

    finally:
        # Always release subclips and the source to free file handles / memory
        for clip in subclips:
            clip.close()
        source.close()

    return output_path


def replace_audio(video_path: str, audio_path: str, output_path: str) -> str:
    """
    Replace the audio track of a video with a separate audio file via FFmpeg.

    Uses a direct FFmpeg subprocess call rather than MoviePy because FFmpeg is
    more reliable for muxing pre-rendered audio (e.g. denoised / enhanced
    tracks) without re-encoding the video stream.

    Args:
        video_path:  Path to the source video file (video stream is kept as-is).
        audio_path:  Path to the replacement audio file.
        output_path: Destination path for the output video.

    Returns:
        output_path on success.

    Raises:
        subprocess.CalledProcessError: If FFmpeg exits with a non-zero status.
    """
    print(f"Replacing audio track...")
    print(f"  Video : {video_path}")
    print(f"  Audio : {audio_path}")
    print(f"  Output: {output_path}")

    cmd = [
        FFMPEG_BIN,
        "-y",                    # Overwrite output without prompting
        "-i", video_path,        # Input 0: video source
        "-i", audio_path,        # Input 1: replacement audio
        "-map", "0:v:0",         # Take video stream from input 0
        "-map", "1:a:0",         # Take audio stream from input 1
        "-c:v", "copy",          # Copy video stream — no re-encode
        "-c:a", "aac",           # Encode audio as AAC
        "-shortest",             # Trim to the shorter of the two inputs
        output_path,
    ]

    subprocess.run(cmd, check=True)

    print(f"Audio replacement complete: {output_path}")
    return output_path
