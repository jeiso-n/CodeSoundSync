# CodeSound Sync

CodeSound Sync is a local-first Windows desktop application for ordinary video creators that adds natural keyboard typing and mouse-click sound effects to programming tutorial recordings—including sped-up coding footage—so the exported WAV track can be dropped directly into Premiere Pro, DaVinci Resolve, CapCut, or any other video editor.

It runs completely offline using local FFmpeg/FFprobe and Python audio synthesis, without requiring cloud accounts, API keys, or technical knowledge.

## Creative Workflow (4 Steps)

1. **1. Video** — Import a local screen recording (`MP4`, `MOV`, `MKV`, `AVI`, `M4V`, `WebM`), preview playback, and click **Detect Activity**.
2. **2. Review** — Inspect detected keyboard taps (blue bars), mouse clicks (green/teal diamonds), and uncertain visual changes (dashed amber rings) on the timeline. Filter by event type, drag markers to adjust timing, or add/remove/reclassify events without losing manual work on re-detection.
3. **3. Sound** — Choose a quick preset (**Crisp Mechanical**, **Soft Laptop**, **Podcast Studio**), customize keyboard and mouse sound styles and volumes, toggle natural human variation, and preview individual sounds or the full synchronized mix.
4. **4. Export** — Choose your output folder and click **Export Audio (WAV)** to render a 44.1 kHz, 16-bit PCM `.wav` track ready for Premiere Pro, DaVinci Resolve, and CapCut.

Optional troubleshooting logs are tucked cleanly behind **Details** in the header so they never clutter the creative workspace.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer (verified on Python 3.14.10 64-bit)
- FFmpeg and FFprobe available on `PATH` (verified with FFmpeg/FFprobe 9.0.1)

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
  ui/           # MainWindow, 4-step workflow panels (Video, Review, Sound, Export), timeline, dialogs, workers
  utils/
tests/
```

## Current Limitations

- Heuristic visual detection cannot prove physical keypresses or distinguish left vs. right mouse buttons automatically; users can reclassify or add click events directly on the timeline.
- Visual preview streams downscaled frames without original video audio; audio preview plays the synthesized sound-effects track.
- Exported WAV timestamps match the imported video's timeline.
