# CodeSound Sync — Current Project Report

**Date:** 2026-11-20  
**Repository:** `D:\Projects\CodeSoundSync` (`main`)  
**Environment:** Windows 11, Python 3.14.10, PySide6-Essentials 6.12.0, FFmpeg/FFprobe 9.0.1  

---

## 1. Project Status

CodeSound Sync is **feature-complete** for local video import, FFmpeg preview, heuristic visual-activity detection, interactive timeline editing, non-destructive re-analysis, realistic sound synthesis & previewing, project persistence, and editor-compatible 44.1 kHz 16-bit PCM WAV export.

---

## 2. Implemented Features & Architecture

### Models (`src/codesound_sync/models/`)
- `MediaInfo` (`media_info.py`): Immutable video/audio metadata parsed from FFprobe JSON.
- `ActivityCandidate` & `ActivityAnalysisResult` (`activity_candidate.py`): Heuristic detection output with `event_timestamps: tuple[float, ...]` preserving individual tap timestamps across typing bursts and `to_sound_events()`.
- `TimelineEvent` (`timeline_event.py`): Editable timeline item (`event_id`, `timestamp_seconds`, `classification`, `enabled`, `source`, `confidence`, `evidence`, `intensity`, `variation`, `user_edited`) with `candidates_to_timeline_events()` (expanding multi-tap typing bursts) and `merge_detected_timeline_events()` (preserving `MANUAL` and `user_edited=True` events when re-running analysis).
- `Project` (`project.py`): Mutable project container with backward-compatible JSON serialization for `timeline_events`.
- `SoundEvent` (`sound_event.py`): Immutable renderable sound event.

### Services (`src/codesound_sync/services/`)
- `ffmpeg_service.py`: Safe argument-list `ffprobe` / `ffmpeg` invocation with UTF-8 decoding (`errors="replace"`), supporting Windows paths with spaces, Unicode, and emojis.
- `activity_analysis_service.py`: Streams `160x90` grayscale frames from FFmpeg, measures both changed pixel fraction and changed row fraction (`_measure_frame_change()`), classifies widespread changes (scene cuts, scrolling) as `UNCERTAIN`, and clusters localized changes into typing bursts with exact tap timestamps.
- `video_preview_service.py`: FFmpeg single-frame RGB24 extraction (with EOF fallback) and continuous preview streaming.
- `sound_generator.py`: Percussive transient + damped body/click resonance synthesis for `KEYBOARD_TAP`, `MOUSE_LEFT_CLICK` (double-transient), and `MOUSE_RIGHT_CLICK` using Python stdlib only.
- `sound_effects_service.py`: Block-mixed 44.1 kHz 16-bit mono PCM WAV renderer (`render()` to file and `render_wav_bytes()` / `render_event_wav_bytes()` to memory) with clipping protection.
- `sound_preview_service.py`: Non-blocking Windows audio preview (`winsound.SND_MEMORY | SND_ASYNC`) for single events (`preview_timeline_event`) and full timeline mixes (`preview_timeline_mix`, `stop`).
- `project_service.py`: Local JSON save/load with schema validation.

### UI & Workers (`src/codesound_sync/ui/`)
- `MainWindow` (`main_window.py`): Connects top-level **Import Video**, **Open Project**, and **Analyze Video** (wired to real analysis), configurable **Detection interval** (`0.25 s`, `0.50 s`, `1.00 s`), project save/load, and graceful worker/audio shutdown in `closeEvent`.
- `WorkspacePanel` (`panels/workspace_panel.py`): Video frame canvas, Play/Pause, `-0.25s`/`+0.25s` stepping, coalesced seek slider, `TimelineWidget`, and `EventInspectorPanel`.
- `TimelineWidget` (`panels/timeline_widget.py`): Painted time ruler, playhead, color-coded event markers, click-to-seek, drag-to-move, overlapping marker cycling, and `Delete`/`Backspace` removal.
- `EventInspectorPanel` (`panels/event_inspector_panel.py`): Add/delete/reclassify/toggle/tune events, **Preview Sound**, **Try Variation**, **Preview Mix**, **Stop Audio**, and **Export Timeline WAV**.
- `ActivityReviewDialog` (`dialogs/activity_review_dialog.py`): Selective candidate review with **Apply Selected to Timeline** (non-destructive merge) and **Generate Sound Effects Track**.
- Background `QThread` workers: `FFprobeWorker`, `ActivityAnalysisWorker`, and `VideoFrameWorker`.

---

## 3. Verification Results

- **Full Automated Test Suite**: `.\.venv\Scripts\python.exe -m pytest tests -v` — **113 passed** (including real FFprobe/FFmpeg integration tests with Unicode/emoji paths, scene-cut/scroll rejection, multi-tap cadence, non-destructive re-analysis merge, WAV integrity, project persistence, and Qt UI worker lifecycles).
- **Compile Check**: `.\.venv\Scripts\python.exe -m compileall -q src tests main.py` — **passed**.
- **Diff Check**: `git diff --check` — **passed**.

---

## 4. Known Limitations

- Heuristic visual detection cannot prove physical keypresses or distinguish left vs. right mouse clicks automatically; users adjust/reclassify events on the timeline.
- Visual preview is video-only (no source audio stream playback); audio preview plays the synthesized sound-effects track.
- **Start Recording Session** button remains disabled for a future stage.
