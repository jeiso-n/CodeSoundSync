# CodeSound Sync

CodeSound Sync is a local-first Windows desktop application for preparing programming tutorial videos for synchronized typing and mouse sounds. It provides local project settings and media inspection, a synthetic sound-effects renderer, heuristic video-activity suggestions, and an editable timeline with local video preview. It does not monitor global keyboard or mouse input.

## Requirements

- Python 3.11 or newer; Python 3.14.10 (64-bit) is a verified Windows option for current dependency releases
- FFmpeg and FFprobe available on `PATH` for video inspection
- Windows 10 or newer

Install FFmpeg from a trusted Windows build provider, extract it, and add its `bin` directory (containing both `ffmpeg.exe` and `ffprobe.exe`) to `PATH`. Open a new PowerShell window and confirm both commands are available:

```powershell
ffmpeg -version
ffprobe -version
```

The application can open without FFmpeg, but it will report an actionable error when a video is imported if FFprobe is unavailable.

## Setup and launch (PowerShell)

From the project directory, select the Python version explicitly when creating the virtual environment. For Python 3.14:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

The project-local virtual environment keeps Python packages isolated from the system installation. If PowerShell blocks virtual-environment activation, run the venv interpreter directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

The requirements file specifies minimum versions rather than a lock file, so pip resolves compatible current releases. In particular, Python 3.14 requires a newer PySide6-Essentials release than the declared 6.7.0 minimum.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

Tests cover FFprobe JSON parsing (including missing metadata and audio streams), safe subprocess invocation and missing-tool errors, project persistence, path utilities, sound-effect WAV rendering and preview, local visual-activity analysis, video frame preview, timeline editing, and Qt import/open/generation/review workflows.

## Stage 2 sound-effects demo

Click **Generate Test Sounds** in Project Settings to create a short WAV containing synthetic keyboard taps and left/right mouse clicks. It is saved in the currently configured output directory under a unique `codesound-test-<id>.wav` filename; existing files are never overwritten. The renderer uses only Python's standard-library math, array, and WAV support to synthesize local effects and writes mono, 16-bit PCM at 44,100 Hz. No third-party sound assets are bundled or used. Test events describe sound effects only; the app does not capture typed characters or monitor global input.

## Video activity review and timeline

Import or open a video, then choose **Analyze Video Activity** in Project Settings. FFmpeg samples 160x90 grayscale frames locally at 0.5-second intervals by default, and a background worker compares consecutive samples. Nearby repeated changes are labeled as possible typing-like activity; isolated changes remain uncertain. The heuristics do not identify mouse buttons and cannot prove that a key was pressed. Scrolling, cursor blinking, scene changes, animations, and window movement can produce candidates.

The workspace provides local frame preview, play/pause, seeking, and frame stepping. Activity suggestions appear as editable timeline events. Add, move, reclassify, enable/disable, preview, or delete events in the timeline inspector; manual events and edits are saved in project JSON. Uncertain events are not rendered until reclassified. Export creates a unique `codesound-activity-<id>.wav` containing included effects at source-video timestamps. It is not aligned to edited or speed-changed footage. The current frame preview is not a full-resolution or audio/video playback editor.

## Project layout

```text
main.py
requirements.txt
src/codesound_sync/
  app.py
  config.py
  models/       # Project, media metadata, sound events, and editable timeline events
  services/     # FFmpeg preview, FFprobe, activity analysis, project persistence, sound preview, and WAV rendering
  ui/           # Main window, review dialogs, timeline/workspace panels, and background workers
  utils/
tests/
assets/sounds/  # Reserved for replaceable local effects in a future stage
projects/       # Local saved project files (ignored by Git)
```

## Roadmap

1. Foundation: desktop UI, local project settings, media metadata inspection, and tests
2. Local synthetic keyboard/mouse sound-effects engine
3. Heuristic visual-activity candidates with human review
4. Editable, persistent source-video timeline with local preview and WAV export
5. Improve activity classification and synchronization to edited timelines
6. Packaging and installer
