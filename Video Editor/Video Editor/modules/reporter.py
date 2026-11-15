"""
reporter.py - Edit report generator for the AI video editing pipeline.

Phase 1: Silence Remover
Generates human-readable text reports and console summaries for
silence-removal edit sessions.
"""

import os
from datetime import datetime


def format_timestamp(ms: int) -> str:
    """
    Convert milliseconds to MM:SS.mmm format.

    Args:
        ms: Time value in milliseconds.

    Returns:
        Formatted string, e.g. 65500 -> "01:05.500"
    """
    ms = int(ms)
    total_seconds, milliseconds = divmod(ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def generate_report(
    video_info: dict,
    silences: list,
    analysis_summary: dict,
    keep_segments: list,
    output_path: str,
) -> str:
    """
    Generate a human-readable edit report and write it to output_path.

    Args:
        video_info: Dict with keys such as 'filename', 'duration_ms',
                    'resolution', 'fps'.
        silences:   List of dicts, each with 'start_ms', 'end_ms',
                    and optionally 'duration_ms'.
        analysis_summary: Dict with aggregated stats, e.g.
                    'total_silence_ms', 'silence_count',
                    'new_duration_ms'.
        keep_segments: List of dicts with 'start_ms' and 'end_ms'
                    representing segments that are kept in the output.
        output_path: File path where the .txt report will be written.

    Returns:
        The full report content as a string.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_name = video_info.get("filename", "Unknown")

    original_duration_ms = video_info.get("duration_ms", 0)
    resolution = video_info.get("resolution", "Unknown")
    fps = video_info.get("fps", "Unknown")

    total_silence_ms = analysis_summary.get(
        "total_silence_ms",
        sum(
            s.get("duration_ms", s.get("end_ms", 0) - s.get("start_ms", 0))
            for s in silences
        ),
    )
    silence_count = analysis_summary.get("silence_count", len(silences))
    new_duration_ms = analysis_summary.get(
        "new_duration_ms",
        original_duration_ms - total_silence_ms,
    )

    silence_pct = (
        (total_silence_ms / original_duration_ms * 100)
        if original_duration_ms > 0
        else 0.0
    )
    time_saved_ms = original_duration_ms - new_duration_ms
    reduction_pct = (
        (time_saved_ms / original_duration_ms * 100)
        if original_duration_ms > 0
        else 0.0
    )

    lines = []

    # ------------------------------------------------------------------ #
    # Header                                                               #
    # ------------------------------------------------------------------ #
    lines.append("=" * 60)
    lines.append("  VIDEO EDIT REPORT  --  Silence Remover (Phase 1)")
    lines.append("=" * 60)
    lines.append(f"  Generated : {timestamp}")
    lines.append(f"  Source    : {source_name}")
    lines.append("=" * 60)
    lines.append("")

    # ------------------------------------------------------------------ #
    # Video Info                                                           #
    # ------------------------------------------------------------------ #
    lines.append("VIDEO INFO")
    lines.append("-" * 30)
    lines.append(f"  Duration   : {format_timestamp(original_duration_ms)}")
    lines.append(f"  Resolution : {resolution}")
    lines.append(f"  FPS        : {fps}")
    lines.append("")

    # ------------------------------------------------------------------ #
    # Summary Stats                                                        #
    # ------------------------------------------------------------------ #
    lines.append("SUMMARY")
    lines.append("-" * 30)
    lines.append(f"  Silences found    : {silence_count}")
    lines.append(f"  Total silence     : {format_timestamp(total_silence_ms)}")
    lines.append(f"  Silence in video  : {silence_pct:.1f}%")
    lines.append(f"  Time saved        : {format_timestamp(time_saved_ms)}")
    lines.append("")

    # ------------------------------------------------------------------ #
    # Cuts Made                                                            #
    # ------------------------------------------------------------------ #
    lines.append("CUTS MADE")
    lines.append("-" * 30)

    if silences:
        col_w = 12
        header = (
            f"  {'#':<4} {'Start':<{col_w}} {'End':<{col_w}} {'Duration':<{col_w}}"
        )
        lines.append(header)
        lines.append("  " + "-" * (4 + col_w * 3 + 3))

        for idx, silence in enumerate(silences, start=1):
            start_ms = silence.get("start_ms", 0)
            end_ms = silence.get("end_ms", 0)
            dur_ms = silence.get("duration_ms", end_ms - start_ms)

            row = (
                f"  {idx:<4} "
                f"{format_timestamp(start_ms):<{col_w}} "
                f"{format_timestamp(end_ms):<{col_w}} "
                f"{format_timestamp(dur_ms):<{col_w}}"
            )
            lines.append(row)
    else:
        lines.append("  No cuts made.")

    lines.append("")

    # ------------------------------------------------------------------ #
    # Kept Segments                                                        #
    # ------------------------------------------------------------------ #
    lines.append("KEPT SEGMENTS")
    lines.append("-" * 30)

    if keep_segments:
        col_w = 12
        header = (
            f"  {'#':<4} {'Start':<{col_w}} {'End':<{col_w}} {'Duration':<{col_w}}"
        )
        lines.append(header)
        lines.append("  " + "-" * (4 + col_w * 3 + 3))

        for idx, seg in enumerate(keep_segments, start=1):
            start_ms = seg.get("start_ms", 0)
            end_ms = seg.get("end_ms", 0)
            dur_ms = end_ms - start_ms

            row = (
                f"  {idx:<4} "
                f"{format_timestamp(start_ms):<{col_w}} "
                f"{format_timestamp(end_ms):<{col_w}} "
                f"{format_timestamp(dur_ms):<{col_w}}"
            )
            lines.append(row)
    else:
        lines.append("  No segments kept.")

    lines.append("")

    # ------------------------------------------------------------------ #
    # Output Info                                                          #
    # ------------------------------------------------------------------ #
    lines.append("OUTPUT")
    lines.append("-" * 30)
    lines.append(f"  New duration    : {format_timestamp(new_duration_ms)}")
    lines.append(f"  Reduction       : {reduction_pct:.1f}%")
    lines.append(f"  Report saved to : {output_path}")
    lines.append("")
    lines.append("=" * 60)

    report_content = "\n".join(lines)

    # Write to disk
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(report_content)

    return report_content


def print_summary(analysis_summary: dict, original_duration_ms: int) -> None:
    """
    Print a concise console summary of the silence-removal results.

    Args:
        analysis_summary: Dict with keys 'silence_count',
                          'total_silence_ms', and 'new_duration_ms'.
        original_duration_ms: Original video duration in milliseconds.
    """
    silence_count = analysis_summary.get("silence_count", 0)
    total_silence_ms = analysis_summary.get("total_silence_ms", 0)
    new_duration_ms = analysis_summary.get("new_duration_ms", original_duration_ms)

    silence_pct = (
        (total_silence_ms / original_duration_ms * 100)
        if original_duration_ms > 0
        else 0.0
    )
    reduction_pct = (
        ((original_duration_ms - new_duration_ms) / original_duration_ms * 100)
        if original_duration_ms > 0
        else 0.0
    )

    print()
    print("=" * 40)
    print("  SILENCE REMOVAL SUMMARY")
    print("=" * 40)
    print(f"  Before  : {format_timestamp(original_duration_ms)}")
    print(f"  After   : {format_timestamp(new_duration_ms)}")
    print(f"  Removed : {silence_count} silence(s)  "
          f"({silence_pct:.1f}% of video)")
    print(f"  Saved   : {format_timestamp(original_duration_ms - new_duration_ms)}"
          f"  ({reduction_pct:.1f}% shorter)")
    print("=" * 40)
    print()
