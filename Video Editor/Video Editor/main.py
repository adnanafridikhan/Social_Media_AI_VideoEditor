"""
AI Video Editing Pipeline — Phase 1: Silence Remover

Usage:
    python main.py                          # processes all videos in input/
    python main.py path/to/video.mp4        # processes a single video
"""

import os
import sys
import json
import time

from modules.audio_extractor import extract_audio, get_video_info
from modules.analyzer import detect_silences, generate_cut_list, get_analysis_summary
from modules.cutter import cut_video
from modules.reporter import generate_report, print_summary
from modules.syncer import find_audio_offset, composite_pip, concat_videos
from modules.audio_enhancer import enhance_video_audio
from modules.hook_renderer import render_hook, preprocess_hook
import re

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(ROOT_DIR, "input")
OUTPUT_DIR = os.path.join(ROOT_DIR, "output")
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}


def load_config() -> dict:
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    print("[main] config.json not found, using defaults.")
    return {}


def process_video(video_path: str, config: dict) -> None:
    stem = os.path.splitext(os.path.basename(video_path))[0]
    video_output_dir = os.path.join(OUTPUT_DIR, stem)
    os.makedirs(video_output_dir, exist_ok=True)

    start_time = time.time()

    print(f"\n{'='*60}")
    print(f"  Processing: {os.path.basename(video_path)}")
    print(f"{'='*60}\n")

    # --- Step 1: Get video info ---
    print("[1/4] Getting video info...")
    info = get_video_info(video_path)
    duration_s = info.get("duration", 0)
    duration_ms = int(duration_s * 1000)

    # --- Step 2: Extract audio ---
    print("\n[2/4] Extracting audio...")
    audio_paths = extract_audio(video_path, video_output_dir)
    analysis_audio = audio_paths["analysis_audio"]

    # --- Step 3: Detect silences & generate cut list ---
    print("\n[3/4] Analyzing audio for silences...")
    silence_config = config.get("silence", {})
    silences = detect_silences(analysis_audio, silence_config)

    keep_pause_ms = silence_config.get("keep_pause_ms", 250)
    keep_segments = generate_cut_list(silences, duration_ms, keep_pause_ms)
    summary = get_analysis_summary(silences, duration_ms)

    if not silences:
        print("  No significant silences detected — video is already clean!")
        return

    # Print quick console summary
    new_duration_ms = sum(s["duration_ms"] for s in keep_segments)
    report_summary = {
        "silence_count": summary["total_silences"],
        "total_silence_ms": summary["total_silence_duration_ms"],
        "new_duration_ms": new_duration_ms,
    }
    print_summary(report_summary, duration_ms)

    # --- Step 4: Cut video ---
    print("[4/4] Cutting video...")
    crossfade_ms = config.get("output", {}).get("crossfade_ms", 50)
    output_video = os.path.join(video_output_dir, f"{stem}_edited.mp4")
    cut_video(video_path, keep_segments, output_video, crossfade_ms=crossfade_ms)

    # --- Generate report ---
    if config.get("output", {}).get("generate_report", True):
        report_path = os.path.join(video_output_dir, f"{stem}_report.txt")
        video_report_info = {
            "filename": os.path.basename(video_path),
            "duration_ms": duration_ms,
            "resolution": f"{info.get('width', '?')}x{info.get('height', '?')}",
            "fps": info.get("fps", "?"),
        }
        generate_report(video_report_info, silences, report_summary, keep_segments, report_path)
        print(f"\n  Report saved: {report_path}")

    elapsed = time.time() - start_time
    print(f"\n  Done! Output: {output_video}")
    print(f"  Total time: {elapsed:.1f}s")

    # Cleanup temp audio files
    for key in ("analysis_audio", "hq_audio"):
        path = audio_paths.get(key)
        if path and os.path.isfile(path):
            os.remove(path)
    print("  Temp audio files cleaned up.")


def find_hook_input(input_dir: str) -> tuple | None:
    """
    Detect a hook clip in input_dir. `hook.json` is optional; the official
    TikTok template doesn't currently consume per-hook config fields, so a
    bare `hook.<ext>` is enough to trigger the hook flow.

    Returns (hook_video_path, hook_config_path_or_None) or None if no hook
    video is present.
    """
    if not os.path.isdir(input_dir):
        return None

    hook_video = None
    for ext in VIDEO_EXTENSIONS:
        candidate = os.path.join(input_dir, f"hook{ext}")
        if os.path.isfile(candidate):
            hook_video = candidate
            break

    if not hook_video:
        return None

    hook_config = os.path.join(input_dir, "hook.json")
    if not os.path.isfile(hook_config):
        hook_config = None
    return (hook_video, hook_config)


def render_hook_once(hook_paths: tuple, config: dict) -> str | None:
    """
    Silence-cut and render the hook video at most once per pipeline run.
    Subsequent calls return the cached output path. Returns None on failure
    (logged).
    """
    if not hook_paths:
        return None
    if getattr(render_hook_once, "_cached_path", None):
        return render_hook_once._cached_path

    hook_video, hook_config = hook_paths
    hook_cfg = config.get("hook", {})
    remotion_dir = hook_cfg.get("remotion_dir")
    if remotion_dir and not os.path.isabs(remotion_dir):
        remotion_dir = os.path.join(ROOT_DIR, remotion_dir)

    print(f"\n{'='*60}")
    print(f"  Phase 0: Hook preprocessing + render")
    print(f"{'='*60}\n")

    try:
        cut_video_path, cut_duration_s = preprocess_hook(
            hook_video, OUTPUT_DIR, config
        )
    except Exception as e:
        print(f"[main] Hook silence-cut failed: {e}")
        print(f"[main] Falling back to raw hook clip.")
        cut_video_path, cut_duration_s = hook_video, None

    output_path = os.path.join(OUTPUT_DIR, "hook_rendered.mp4")
    try:
        render_hook(
            cut_video_path,
            hook_config,
            output_path,
            remotion_dir=remotion_dir,
            duration_override=cut_duration_s,
        )
    except Exception as e:
        print(f"[main] Hook render failed: {e}")
        print(f"[main] Continuing without hook prepend.")
        render_hook_once._cached_path = None
        return None

    render_hook_once._cached_path = output_path
    return output_path


def prepend_hook(rendered_hook_path: str, main_video_path: str,
                 output_path: str) -> str:
    """Concatenate [hook, main] -> output_path via FFmpeg filter concat."""
    print(f"\n{'='*60}")
    print(f"  Phase 0: Prepending hook -> {os.path.basename(output_path)}")
    print(f"{'='*60}\n")
    concat_videos([rendered_hook_path, main_video_path], output_path)
    print(f"  Final (with hook): {output_path}")
    return output_path


def find_dual_inputs(input_dir: str) -> list:
    """
    Find phone+screen pairs in input_dir.

    Supports two naming conventions:
      - Single segment: phone.mp4 + screen.mp4
      - Multi-segment:  phone1.mp4 + screen1.mp4, phone2.mp4 + screen2.mp4, ...

    Returns a list of (phone_path, screen_path) tuples sorted by segment number.
    Single-segment is treated as segment 0.
    Returns [] if no valid pair is found.
    """
    pat = re.compile(r"^(phone|screen)(\d*)$", re.IGNORECASE)
    phones, screens = {}, {}

    for f in os.listdir(input_dir):
        stem, ext = os.path.splitext(f)
        if ext.lower() not in VIDEO_EXTENSIONS:
            continue
        m = pat.match(stem)
        if not m:
            continue
        kind = m.group(1).lower()
        idx = int(m.group(2)) if m.group(2) else 0
        target = phones if kind == "phone" else screens
        target[idx] = os.path.join(input_dir, f)

    pairs = []
    common = sorted(set(phones) & set(screens))
    for idx in common:
        pairs.append((phones[idx], screens[idx]))

    orphans = (set(phones) ^ set(screens))
    if orphans:
        for idx in sorted(orphans):
            label = f"{idx}" if idx > 0 else "(unnumbered)"
            kind = "phone" if idx in phones else "screen"
            print(f"[main] Warning: {kind}{label} has no matching pair — skipping.")

    return pairs


def process_dual_inputs(pairs: list, config: dict, hook_paths: tuple | None = None) -> None:
    """
    Process one or more (phone, screen) pairs:
      1. For each pair: sync + composite -> mergedN.mp4
      2. Concatenate all mergedN.mp4 in order -> merged.mp4
      3. Run Phase 1 silence removal -> merged_edited.mp4
      4. Run audio enhancement -> merged_edited_enhanced.mp4
    """
    project_out = os.path.join(OUTPUT_DIR, "composited")
    os.makedirs(project_out, exist_ok=True)

    composite_cfg = config.get("composite", {})
    sample_s = composite_cfg.get("sync_sample_seconds", 60)

    segment_paths = []
    for i, (phone_path, screen_path) in enumerate(pairs, start=1):
        seg_name = f"merged{i}.mp4" if len(pairs) > 1 else "merged.mp4"
        seg_path = os.path.join(project_out, seg_name)

        if os.path.isfile(seg_path) and os.path.getsize(seg_path) > 0:
            print(f"\n[main] Segment {i}/{len(pairs)} already done — skipping "
                  f"({os.path.basename(seg_path)})")
            segment_paths.append(seg_path)
            continue

        print(f"\n{'='*60}")
        print(f"  Phase 1.5: Segment {i}/{len(pairs)} — Sync + Composite")
        print(f"{'='*60}")
        print(f"  Phone : {phone_path}")
        print(f"  Screen: {screen_path}\n")

        offset_s = find_audio_offset(phone_path, screen_path, project_out, sample_s)
        composite_pip(phone_path, screen_path, offset_s, seg_path, composite_cfg)
        segment_paths.append(seg_path)

    # Concatenate (or rename single segment)
    merged_path = os.path.join(project_out, "merged.mp4")
    if len(segment_paths) > 1:
        if os.path.isfile(merged_path) and os.path.getsize(merged_path) > 0:
            print(f"\n[main] Concatenated file already exists — skipping concat "
                  f"({os.path.basename(merged_path)})")
        else:
            print(f"\n{'='*60}")
            print(f"  Phase 1.6: Concatenating {len(segment_paths)} segments")
            print(f"{'='*60}\n")
            concat_videos(segment_paths, merged_path)

    # Phase 1: silence removal (skip if already cut)
    stem = os.path.splitext(os.path.basename(merged_path))[0]
    edited_path = os.path.join(OUTPUT_DIR, stem, f"{stem}_edited.mp4")
    if os.path.isfile(edited_path) and os.path.getsize(edited_path) > 0:
        print(f"\n[main] Silence-cut file already exists — skipping Phase 1 "
              f"({os.path.basename(edited_path)})")
    else:
        process_video(merged_path, config)

    # Phase 2 (lite): audio enhancement on the silence-cut output
    enhance_cfg = config.get("audio_enhancement", {})
    if enhance_cfg.get("enabled", True):
        if not os.path.isfile(edited_path):
            print(f"[main] Skipping audio enhancement — {edited_path} not found.")
            return
        enhanced_path = os.path.join(os.path.dirname(edited_path),
                                     f"{stem}_edited_enhanced.mp4")
        if os.path.isfile(enhanced_path) and os.path.getsize(enhanced_path) > 0:
            print(f"\n[main] Enhanced file already exists — skipping enhancement "
                  f"({os.path.basename(enhanced_path)})")
        else:
            print(f"\n{'='*60}")
            print(f"  Phase 2: Audio Enhancement")
            print(f"{'='*60}\n")
            enhance_video_audio(edited_path, enhanced_path, enhance_cfg)
        print(f"\n  Both files kept for A/B comparison:")
        print(f"    Original cut: {edited_path}")
        print(f"    Enhanced:     {enhanced_path}")

        main_for_hook = enhanced_path
    else:
        main_for_hook = os.path.join(project_out, "merged_edited.mp4")

    # Hook prepend (optional)
    if hook_paths and config.get("hook", {}).get("enabled", True):
        rendered = render_hook_once(hook_paths, config)
        if rendered and os.path.isfile(main_for_hook):
            final_path = os.path.join(project_out, "final.mp4")
            prepend_hook(rendered, main_for_hook, final_path)


def main():
    config = load_config()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Single video mode (CLI arg) — no hook handling here on purpose.
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        if not os.path.isfile(video_path):
            print(f"Error: File not found: {video_path}")
            sys.exit(1)
        process_video(video_path, config)
        return

    if not os.path.isdir(INPUT_DIR):
        os.makedirs(INPUT_DIR, exist_ok=True)
        print(f"No videos found. Drop video files into: {INPUT_DIR}")
        sys.exit(0)

    hook_paths = find_hook_input(INPUT_DIR)
    if hook_paths:
        print(f"[main] Hook detected: {os.path.basename(hook_paths[0])} "
              f"+ hook.json — will prepend to final output.")

    # Dual-input mode: phone(N).* + screen(N).* pairs present in input/
    if config.get("composite", {}).get("enabled", True):
        pairs = find_dual_inputs(INPUT_DIR)
        if pairs:
            print(f"[main] Found {len(pairs)} phone+screen pair(s) — "
                  f"running composite pipeline.")
            process_dual_inputs(pairs, config, hook_paths=hook_paths)
            print(f"\n{'='*60}")
            print(f"  All done! Check: {OUTPUT_DIR}")
            print(f"{'='*60}")
            return

    # Batch mode — process all standalone videos in input/
    # Exclude the hook clip itself so it isn't silence-cut as a normal video.
    videos = [
        os.path.join(INPUT_DIR, f)
        for f in os.listdir(INPUT_DIR)
        if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
        and os.path.splitext(f)[0].lower() != "hook"
    ]

    if not videos:
        # Hook-only mode: render just the styled hook and exit.
        if hook_paths and config.get("hook", {}).get("enabled", True):
            print("[main] No main videos found — running hook-only mode.")
            rendered = render_hook_once(hook_paths, config)
            if rendered:
                print(f"\n{'='*60}")
                print(f"  Hook-only render done: {rendered}")
                print(f"{'='*60}")
            sys.exit(0)

        print(f"No video files found in: {INPUT_DIR}")
        print(f"Supported formats: {', '.join(sorted(VIDEO_EXTENSIONS))}")
        print(f"Or drop a phone.mp4 + screen.mp4 pair for auto-sync + PiP composite.")
        sys.exit(0)

    print(f"Found {len(videos)} video(s) to process.\n")

    hook_enabled = config.get("hook", {}).get("enabled", True)

    for i, video_path in enumerate(videos, start=1):
        print(f"\n[Video {i}/{len(videos)}]")
        process_video(video_path, config)

        if hook_paths and hook_enabled:
            stem = os.path.splitext(os.path.basename(video_path))[0]
            edited = os.path.join(OUTPUT_DIR, stem, f"{stem}_edited.mp4")
            if not os.path.isfile(edited):
                continue
            rendered = render_hook_once(hook_paths, config)
            if rendered:
                final_path = os.path.join(OUTPUT_DIR, stem, "final.mp4")
                prepend_hook(rendered, edited, final_path)

    print(f"\n{'='*60}")
    print(f"  All done! Check the output folder: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
