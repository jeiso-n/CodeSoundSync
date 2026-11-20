from __future__ import annotations

import time
import wave
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFileDialog, QPlainTextEdit

from codesound_sync.models.activity_candidate import (
    ActivityAnalysisResult,
    ActivityCandidate,
    ActivityType,
)
from codesound_sync.models.media_info import MediaInfo
from codesound_sync.models.project import Project
from codesound_sync.services.activity_analysis_service import ActivityAnalysisCancelled
from codesound_sync.services.project_service import ProjectService
from codesound_sync.ui.main_window import MainWindow, PROJECT_FILTER
from codesound_sync.ui.workers import ffprobe_worker


def test_window_import_runs_probe_in_background(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"local video")
    result = MediaInfo(
        path=video,
        duration_seconds=42.0,
        width=1280,
        height=720,
        frame_rate=30.0,
        video_codec="h264",
        audio_codec="aac",
        bit_rate_kbps=1500,
        size_bytes=1024,
        audio_streams=("aac",),
    )

    def slow_probe(path: Path) -> MediaInfo:
        time.sleep(0.15)
        return result

    monkeypatch.setattr(ffprobe_worker, "probe_media", slow_probe)
    window = MainWindow()
    window._project_service = ProjectService(tmp_path / "projects")
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle() == "CodeSound Sync"
    assert window.step_stack.currentIndex() == 0
    assert "Choose a video to get started" in window.friendly_status_label.text()

    timer_ticks: list[bool] = []
    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(lambda: timer_ticks.append(True))
    timer.start()
    window.load_video(video)
    assert not window.video_step.detect_activity_button.isEnabled()
    qtbot.waitUntil(lambda: window._probe_worker is None, timeout=3000)
    timer.stop()

    assert timer_ticks
    assert window.video_step.detect_activity_button.isEnabled()
    assert window.save_project_button.isEnabled()
    assert "lesson.mp4" in window.video_step.video_name_label.text()
    assert "00:00:42" in window.video_step.video_meta_label.text()
    assert "Your video is ready" in window.friendly_status_label.text()


def test_window_shows_friendly_missing_ffprobe_error(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"local video")

    def missing_probe(path: Path) -> MediaInfo:
        from codesound_sync.services.ffmpeg_service import FFmpegNotFoundError

        raise FFmpegNotFoundError("ffprobe was not found on PATH.")

    monkeypatch.setattr(ffprobe_worker, "probe_media", missing_probe)
    window = MainWindow()
    qtbot.addWidget(window)
    window.load_video(video)
    qtbot.waitUntil(lambda: window._probe_worker is None, timeout=3000)

    assert not window.video_step.detect_activity_button.isEnabled()
    assert window.status_details_button.isVisible() or "Could not inspect this video" in window.friendly_status_label.text()
    assert "ffprobe was not found on PATH" in window.status_panel.findChild(
        QPlainTextEdit
    ).toPlainText()


def test_open_project_restores_fields_and_warns_for_missing_video(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "missing-lesson.mp4"
    project = Project(
        name="Saved Lesson",
        source_video=source,
        output_dir=tmp_path / "rendered",
        media_info=MediaInfo(
            path=source,
            duration_seconds=125,
            width=1920,
            height=1080,
            frame_rate=30.0,
            video_codec="h264",
            audio_codec="aac",
            bit_rate_kbps=1200,
            size_bytes=2048,
            audio_streams=("aac",),
        ),
    )
    service = ProjectService(tmp_path / "projects")
    project_file = service.save(project)
    window = MainWindow()
    window._project_service = service
    qtbot.addWidget(window)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args: (str(project_file), PROJECT_FILTER),
    )

    window.open_project_button.click()

    assert window.open_project_button.isEnabled()
    assert window._project == project
    assert window._project_file == project_file
    assert window.export_step.project_name_edit.text() == "Saved Lesson"
    assert window.export_step.output_location_edit.text() == str(tmp_path / "rendered")
    assert "Video file not found" in window.video_preview._preview.text()
    assert "original video file could not be found" in window.friendly_status_label.text()


def test_open_project_dialog_cancel_preserves_current_project(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    current_project = Project(name="Current Project")
    current_project_file = tmp_path / "current.json"
    window._project = current_project
    window._project_file = current_project_file
    window.export_step.project_name_edit.setText(current_project.name)
    qtbot.addWidget(window)
    dialog_args: list[tuple] = []

    def cancel_dialog(*args: object) -> tuple[str, str]:
        dialog_args.append(args)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", cancel_dialog)
    window.open_project_button.click()

    assert window._project is current_project
    assert window._project_file == current_project_file
    assert window.export_step.project_name_edit.text() == "Current Project"
    assert len(dialog_args) == 1
    assert dialog_args[0][1] == "Open Project"
    assert dialog_args[0][3] == PROJECT_FILTER


def test_open_project_rejects_malformed_file_without_replacing_state(
    qtbot, tmp_path: Path
) -> None:
    window = MainWindow()
    current_project = Project(name="Current Project")
    window._project = current_project
    window.export_step.project_name_edit.setText(current_project.name)
    qtbot.addWidget(window)
    malformed = tmp_path / "broken.json"
    malformed.write_text("{broken", encoding="utf-8")

    assert not window.load_project(malformed)

    assert window._project is current_project
    assert window.export_step.project_name_edit.text() == "Current Project"
    assert "could not be opened" in window.friendly_status_label.text()


def test_save_loaded_project_updates_selected_file(
    qtbot, tmp_path: Path
) -> None:
    service = ProjectService(tmp_path / "projects")
    original = Project(
        name="Original",
        source_video=tmp_path / "lesson.mp4",
        output_dir=tmp_path / "output",
    )
    project_file = service.save(original)
    window = MainWindow()
    window._project_service = service
    qtbot.addWidget(window)

    assert window.load_project(project_file)
    window.export_step.project_name_edit.setText("Renamed")
    window.export_step.output_location_edit.setText(str(tmp_path / "new-output"))
    window._save_project()

    loaded = service.load_file(project_file)
    assert loaded.project_id == original.project_id
    assert loaded.name == "Renamed"
    assert loaded.output_dir == tmp_path / "new-output"
    assert list((tmp_path / "projects").glob("*.json")) == [project_file]


def test_activity_analysis_runs_in_background_and_switches_to_review(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    import codesound_sync.ui.main_window as main_window_module

    source = tmp_path / "tutorial.mp4"
    source.write_bytes(b"synthetic")
    result = ActivityAnalysisResult(
        candidates=(
            ActivityCandidate(
                0.4,
                ActivityType.TYPING,
                0.55,
                "Repeated visual changes; possible typing-like activity.",
                change_count=3,
                event_timestamps=(0.4, 0.8),
            ),
            ActivityCandidate(
                1.2,
                ActivityType.UNCERTAIN,
                0.3,
                "One isolated visual change.",
            ),
        ),
        sample_interval_seconds=0.5,
        sampled_frame_count=3,
        video_duration_seconds=2.0,
    )

    class SlowAnalyzer:
        def __init__(self, sample_interval_seconds: float) -> None:
            self.sample_interval_seconds = sample_interval_seconds

        def analyze_video(
            self, path: Path, *, cancel_event, progress_callback
        ) -> ActivityAnalysisResult:
            progress_callback("Synthetic sampling in progress.")
            time.sleep(0.15)
            return result

    monkeypatch.setattr(main_window_module, "FrameActivityAnalyzer", SlowAnalyzer)
    window = MainWindow()
    qtbot.addWidget(window)
    output_dir = tmp_path / "output"
    window.export_step.output_location_edit.setText(str(output_dir))
    window._project = Project(name="Tutorial", source_video=source)
    window.video_step.show_loaded_video(source)
    window.video_step.detect_activity_button.setEnabled(True)
    window.show()

    timer_ticks: list[bool] = []
    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(lambda: timer_ticks.append(True))
    timer.start()
    window.video_step.detect_activity_button.click()
    qtbot.waitUntil(lambda: window._activity_worker is None, timeout=3000)
    timer.stop()

    assert timer_ticks
    assert window.step_stack.currentIndex() == 1
    assert len(window.review_step.timeline_widget.events) == 3
    assert "Activity detection complete" in window.friendly_status_label.text()

    # Switch to Export and export WAV
    window._switch_step(3)
    window.export_step.export_audio_button.click()
    generated = list(output_dir.glob("codesound-activity-*.wav"))
    assert len(generated) == 1
    with wave.open(str(generated[0]), "rb") as wav_file:
        assert wav_file.getframerate() == 44_100
        assert wav_file.getnframes() >= 2 * 44_100
    assert window.export_step.success_card.isVisible()


def test_activity_analysis_cancel_and_worker_error_are_reported(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    import codesound_sync.ui.main_window as main_window_module

    source = tmp_path / "tutorial.mp4"
    source.write_bytes(b"synthetic")

    class CancellableAnalyzer:
        def __init__(self, sample_interval_seconds: float) -> None:
            pass

        def analyze_video(
            self, path: Path, *, cancel_event, progress_callback
        ) -> ActivityAnalysisResult:
            progress_callback("Waiting for cancellation.")
            cancel_event.wait(2)
            if cancel_event.is_set():
                raise ActivityAnalysisCancelled("Activity analysis was cancelled.")
            return ActivityAnalysisResult((), 0.5, 0, 0.0)

    monkeypatch.setattr(
        main_window_module, "FrameActivityAnalyzer", CancellableAnalyzer
    )
    window = MainWindow()
    qtbot.addWidget(window)
    media_info = MediaInfo(
        path=source,
        duration_seconds=10.0,
        width=1280,
        height=720,
        frame_rate=30.0,
        video_codec="h264",
        audio_codec="aac",
        bit_rate_kbps=1000,
        size_bytes=512,
        audio_streams=("aac",),
    )
    window._project = Project(name="Tutorial", source_video=source, media_info=media_info)
    window.video_step.show_loaded_video(source, media_info=media_info)
    window.show()

    window.video_step.detect_activity_button.click()
    qtbot.waitUntil(lambda: window.video_step.progress_card.isVisible(), timeout=1000)
    window.video_step.cancel_detect_button.click()
    qtbot.waitUntil(lambda: window._activity_worker is None, timeout=3000)
    assert "cancelled" in window.friendly_status_label.text().lower()

    class FailingAnalyzer:
        def __init__(self, sample_interval_seconds: float) -> None:
            pass

        def analyze_video(self, path: Path, **kwargs: object) -> ActivityAnalysisResult:
            raise RuntimeError("synthetic FFmpeg decode error")

    monkeypatch.setattr(main_window_module, "FrameActivityAnalyzer", FailingAnalyzer)
    window.video_step.detect_activity_button.click()
    qtbot.waitUntil(lambda: window._activity_worker is None, timeout=3000)
    assert "Could not detect activity" in window.friendly_status_label.text()
    assert "synthetic FFmpeg decode error" in window.status_panel.findChild(
        QPlainTextEdit
    ).toPlainText()


def test_window_import_unicode_video_populates_media_info_and_reports_probe_errors(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace
    from codesound_sync.services import ffmpeg_service

    video = tmp_path / "How To Use Primary Keys In MySQL Workbench 🥶.mp4"
    video.write_bytes(b"synthetic video")
    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", lambda: Path("ffprobe.exe"))
    monkeypatch.setattr(
        ffmpeg_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                '{"format":{"filename":"How To Use Primary Keys In MySQL Workbench 🥶.mp4",'
                '"duration":"95.0","size":"4096","bit_rate":"1200000"},'
                '"streams":[{"codec_type":"video","width":1920,"height":1080,'
                '"r_frame_rate":"30/1","codec_name":"h264"},'
                '{"codec_type":"audio","codec_name":"aac"}]}'
            ),
            stderr="",
        ),
    )

    window = MainWindow()
    qtbot.addWidget(window)
    window.load_video(video)
    qtbot.waitUntil(lambda: window._probe_worker is None, timeout=3000)

    assert "00:01:35" in window.video_step.video_meta_label.text()
    assert "1920×1080" in window.video_step.video_meta_label.text()
    assert window.video_step.detect_activity_button.isEnabled()

    monkeypatch.setattr(
        ffmpeg_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=None, stderr=""
        ),
    )
    window.load_video(video)
    qtbot.waitUntil(lambda: window._probe_worker is None, timeout=3000)

    assert "Could not inspect this video" in window.friendly_status_label.text()
    log_text = window.status_panel.findChild(QPlainTextEdit).toPlainText()
    assert "returned no media metadata output" in log_text
    assert "TypeError" not in log_text
