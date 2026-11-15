"""
analyzer.py — Phase 1: Silence Remover
Detects silent segments in audio and generates a cut list of segments to keep.
"""

import os

try:
    import imageio_ffmpeg
    _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    os.environ["PATH"] = os.path.dirname(_ffmpeg) + os.pathsep + os.environ.get("PATH", "")
except ImportError:
    pass

from pydub import AudioSegment
from pydub.silence import detect_silence


def detect_silences(audio_path: str, config: dict) -> list:
    """
    Detect silent segments in a WAV audio file.

    Args:
        audio_path: Path to the WAV file.
        config: Dict with optional keys:
            - threshold_db (int): dBFS level below which audio is considered silent. Default: -40.
            - min_duration_ms (int): Minimum silence length to include. Default: 500.
            - keep_pause_ms (int): Stored for downstream use; not used in detection. Default: 250.

    Returns:
        List of dicts: [{"start_ms": int, "end_ms": int, "duration_ms": int, "type": "silence"}, ...]
        Only silences longer than min_duration_ms are included.
    """
    threshold_db = config.get("threshold_db", -40)
    min_duration_ms = config.get("min_duration_ms", 500)

    audio = AudioSegment.from_wav(audio_path)

    # detect_silence returns [[start_ms, end_ms], ...] for segments below the threshold.
    raw_silences = detect_silence(
        audio,
        min_silence_len=min_duration_ms,
        silence_thresh=threshold_db,
        seek_step=1,
    )

    silences = []
    for start_ms, end_ms in raw_silences:
        duration_ms = end_ms - start_ms
        silences.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": duration_ms,
            "type": "silence",
        })

    return silences


def generate_cut_list(silences: list, total_duration_ms: int, keep_pause_ms: int) -> list:
    """
    Generate a list of segments to KEEP by inverting the silence list.

    Each detected silence is trimmed inward by keep_pause_ms (split evenly: half retained
    at the tail of the preceding segment, half at the head of the following segment) so
    cuts don't sound abrupt.

    Args:
        silences: Output of detect_silences().
        total_duration_ms: Total audio length in milliseconds.
        keep_pause_ms: Milliseconds of silence to preserve around each cut.

    Returns:
        List of dicts: [{"start_ms": int, "end_ms": int, "duration_ms": int}, ...]
        Segments with zero or negative duration are omitted.
    """
    half_pause = keep_pause_ms // 2
    segments = []
    cursor = 0  # tracks the end of the last kept segment

    for silence in silences:
        silence_start = silence["start_ms"]
        silence_end = silence["end_ms"]

        # End of the kept segment before this silence:
        # extend into the silence by half_pause so we keep a short breath.
        seg_end = silence_start + half_pause

        # Start of the kept segment after this silence:
        # pull back from silence end by half_pause.
        next_start = silence_end - half_pause

        # Clamp to valid range
        seg_end = min(seg_end, silence_end)
        next_start = max(next_start, silence_start)

        if seg_end > cursor:
            duration = seg_end - cursor
            segments.append({
                "start_ms": cursor,
                "end_ms": seg_end,
                "duration_ms": duration,
            })

        cursor = max(cursor, next_start)

    # Append the final segment after the last silence
    if cursor < total_duration_ms:
        segments.append({
            "start_ms": cursor,
            "end_ms": total_duration_ms,
            "duration_ms": total_duration_ms - cursor,
        })

    return segments


def get_analysis_summary(silences: list, total_duration_ms: int) -> dict:
    """
    Summarise silence detection results.

    Args:
        silences: Output of detect_silences().
        total_duration_ms: Total audio length in milliseconds.

    Returns:
        Dict with:
            - total_silences (int)
            - total_silence_duration_ms (int)
            - percentage_silent (float): 0–100, rounded to 2 dp.
            - estimated_time_saved_ms (int): Same as total_silence_duration_ms;
              caller can also factor in keep_pause_ms if desired.
    """
    total_silences = len(silences)
    total_silence_duration_ms = sum(s["duration_ms"] for s in silences)

    if total_duration_ms > 0:
        percentage_silent = round(
            (total_silence_duration_ms / total_duration_ms) * 100, 2
        )
    else:
        percentage_silent = 0.0

    return {
        "total_silences": total_silences,
        "total_silence_duration_ms": total_silence_duration_ms,
        "percentage_silent": percentage_silent,
        "estimated_time_saved_ms": total_silence_duration_ms,
    }
