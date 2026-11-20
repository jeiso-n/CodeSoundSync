# CodeSound Sync

CodeSound Sync is a local-first Windows desktop application that adds realistic keyboard typing and mouse-click sound effects to programming tutorial recordings—including sped-up coding footage—so the exported WAV track can be imported directly into Premiere Pro, DaVinci Resolve, CapCut, or other video editors.

It runs completely offline using local FFmpeg/FFprobe and Python standard-library audio synthesis. It does not monitor global keyboard or mouse input or require any cloud APIs.

## Features

- **Local Video Import & Media Inspection**: Imports `.mp4`, `.mov`, `.mkv`, `.avi`, `.m4v`, and `.webm` files (including paths with spaces and Unicode/emoji characters) and inspects duration, resolution, frame rate, codecs, bit rate, and audio streams via FFprobe.
- **FFmpeg-Backed Video Preview**: Play, pause, scrub, and step (`-0.25s` / `+0.25s`) through source videos with synchronized timeline playhead tracking.
- **Heuristic Visual Activity Analysis**:
  - Samples downsampled grayscale frames via FFmpeg in a background worker (`0.25 s`, `0.50 s`, or `1.00 s` detection interval).
  - Separates localized typing-like bursts (preserving individual tap timestamps across the burst) from widespread frame changes such as scene cuts and scrolling (marked as uncertain).
  - Non-destructive merge: re-running analysis preserves all manually added and user-edited timeline events.
- **Interactive Event Timeline & Inspector**:
  - Visual time ruler, playhead, and color-coded event markers (`Keyboard Tap`, `Mouse Left Click`, `Mouse Right Click`, `Uncertain Activity`).
  - Add events at playhead, drag markers to adjust timestamps, press `Delete` or click **Delete Event**, reclassify uncertain suggestions, toggle inclusion, and tune intensity and variation.
- **Realistic Local Sound Synthesis & Auditioning**:
  - Synthesizes percussive keyboard taps and double-transient mouse clicks (44.1 kHz, 16-bit mono PCM WAV) with deterministic variation to avoid robotic repetition.
  - Audition individual events (**Preview Sound** / **Try Variation**) or the full synchronized mix (**Preview Mix** / **Stop Audio**) before exporting.
- **Project Persistence & Editor-Ready WAV Export**:
  - Save and reopen `.json` project files (backward-compatible with earlier project schemas).
  - Export standard 44.1 kHz 16-bit PCM `.wav` files (`codesound-activity-<id>.wav`) ready for Premiere Pro, DaVinci Resolve, and CapCut.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer (verified on Python 3.14.10 64-bit)
- FFmpeg and FFprobe available on `PATH` (verified with FFmpeg/FFprobe 9.0.1)

Verify FFmpeg and FFprobe in PowerShell:

```powershell
ffmpeg -version
ffprobe -version
```

## Setup and Launch (PowerShell)

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Or run directly via the virtual environment interpreter:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Typical Workflow

1. Click **Import Video** to select a local screen recording.
2. Adjust **Detection interval** (`0.25 s` for fast/sped-up footage, `0.50 s` default) and click **Analyze Video** (or **Analyze Video Activity**).
3. Review detected candidates in the dialog and click **Apply Selected to Timeline** (or **Generate Sound Effects Track**).
4. Use the video preview and timeline to add, drag, reclassify, or delete events without losing manual work.
5. Click **Preview Sound**, **Try Variation**, or **Preview Mix** to audition the audio.
6. Click **Export Timeline WAV** to render the synchronized `.wav` track into your output folder, and **Save Project** to save your work.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

## Project Layout

```text
main.py
requirements.txt
current report.md
src/codesound_sync/
  app.py
  config.py
  models/       # Project, MediaInfo, SoundEvent, ActivityCandidate, TimelineEvent
  services/     # FFprobe, FFmpeg preview, activity analysis, sound generator/effects/preview, project persistence
  ui/           # MainWindow, review dialog, timeline/inspector/workspace/media/status panels, workers
  utils/
tests/
```

## Current Limitations

- Visual activity heuristics cannot prove physical keypresses or distinguish left vs. right mouse buttons automatically; users can reclassify or add click events directly on the timeline.
- Visual preview streams downscaled RGB24 frames without original video audio; audio auditioning plays the synthesized sound-effect track.
- Exported WAV timestamps match the imported video's timeline (`source-video timestamps`). If you re-cut or speed-change the video *after* exporting, re-import the edited clip or adjust events on the timeline.
- **Start Recording Session** remains reserved for a future stage.
