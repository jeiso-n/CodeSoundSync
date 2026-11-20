from __future__ import annotations

import wave
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QPlainTextEdit

from codesound_sync.models.activity_candidate import (
    ActivityAnalysisResult,
    ActivityCandidate,
    ActivityType,
)
from codesound_sync.models.media_info import MediaInfo
from codesound_sync.models.project import Project
from codesound_sync.models.timeline_event import (
    EventClassification,
    EventSource,
    TimelineEvent,
)
from codesound_sync.services.project_service import ProjectService
from codesound_sync.services.sound_preview_service import SoundPreviewService
from codesound_sync.services.video_preview_service import (
    PreviewFrame,
    VideoPreviewError,
    VideoPreviewService,
)
from codesound_sync.ui.main_window import MainWindow


class FakePreviewService(VideoPreviewService):
    """Deterministic in-memory frame decoder for UI tests."""

    def __init__(self, *, should_fail: bool = False) -> None:
        super().__init__(frame_width=32, frame_height=18, preview_fps=20.0)
        self.should_fail = should_fail
        self.extracted_timestamps: list[float] = []

    def extract_frame(
        self, video_path: Path, timestamp_seconds: float = 0.0
    ) -> PreviewFrame:
        self.extracted_timestamps.append(round(float(timestamp_seconds), 3))
        if self.should_fail:
            raise VideoPreviewError("Unsupported codec in test video.")
        return PreviewFrame(
            timestamp_seconds=float(timestamp_seconds),
            width=self.frame_width,
            height=self.frame_height,
            rgb_bytes=bytes([60, 120, 200]) * (self.frame_width * self.frame_height),
        )

    def stream_frames(
        self,
        video_path: Path,
        start_seconds: float = 0.0,
        *,
        fps: float | None = None,
        cancel_event=None,
    ):
        if self.should_fail:
            raise VideoPreviewError("Stream decode failed.")
        for idx in range(3):
            if cancel_event is not None and cancel_event.is_set():
                return
            yield PreviewFrame(
                timestamp_seconds=float(start_seconds) + idx * 0.1,
                width=self.frame_width,
                height=self.frame_height,
                rgb_bytes=bytes([80, 140, 220]) * (self.frame_width * self.frame_height),
            )


def test_video_preview_seek_step_play_and_error_handling(
    qtbot, tmp_path: Path
) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")

    window = MainWindow()
    fake_preview = FakePreviewService()
    window.workspace_panel._preview_service = fake_preview
    qtbot.addWidget(window)
    window.show()

    window._project = Project(
        name="Demo",
        source_video=video,
        media_info=MediaInfo(
            path=video,
            duration_seconds=10.0,
            width=1280,
            height=720,
            frame_rate=30.0,
            video_codec="h264",
            audio_codec="aac",
            bit_rate_kbps=1000,
            size_bytes=512,
            audio_streams=("aac",),
        ),
    )
    window.workspace_panel.set_video(video)
    window.workspace_panel.set_duration(10.0, load_initial_frame=True)
    qtbot.waitUntil(
        lambda: window.workspace_panel._frame_worker is None, timeout=2000
    )

    assert fake_preview.extracted_timestamps == [0.0]
    assert window.workspace_panel._current_pixmap is not None
    assert window.workspace_panel.time_label.text() == "00:00.00 / 00:10.00"

    # Step forward and backward
    window.workspace_panel.step_forward_button.click()
    qtbot.waitUntil(
        lambda: window.workspace_panel._frame_worker is None, timeout=2000
    )
    assert window.workspace_panel.current_seconds == 0.25
    assert window.workspace_panel.timeline_widget.playhead_seconds == 0.25

    window.workspace_panel.step_back_button.click()
    qtbot.waitUntil(
        lambda: window.workspace_panel._frame_worker is None, timeout=2000
    )
    assert window.workspace_panel.current_seconds == 0.0

    # Play stream to completion
    window.workspace_panel.play_pause_button.click()
    qtbot.waitUntil(
        lambda: window.workspace_panel._frame_worker is None, timeout=3000
    )
    assert window.workspace_panel.play_pause_button.text() == "Play"
    assert window.workspace_panel.current_seconds == 10.0

    # Codec error when user explicitly plays an unsupported video
    fake_preview.should_fail = True
    window.workspace_panel.play_pause_button.click()
    qtbot.waitUntil(
        lambda: window.workspace_panel._frame_worker is None, timeout=2000
    )
    log_text = window.status_panel.findChild(QPlainTextEdit).toPlainText()
    assert "Stream decode failed" in log_text


def test_timeline_coordinate_mapping_and_mouse_drag_editing(
    qtbot, tmp_path: Path
) -> None:
    window = MainWindow()
    window.workspace_panel._preview_service = FakePreviewService()
    qtbot.addWidget(window)
    window.resize(1100, 720)
    window.show()

    timeline = window.workspace_panel.timeline_widget
    timeline.resize(600, 90)
    window.workspace_panel.set_duration(20.0, load_initial_frame=False)

    # Coordinate round-trip
    mid_x = timeline.time_to_x(10.0)
    assert abs(timeline.x_to_time(mid_x) - 10.0) <= 0.05

    # Populate events from activity analysis
    result = ActivityAnalysisResult(
        candidates=(
            ActivityCandidate(
                4.0,
                ActivityType.TYPING,
                0.56,
                "4 nearby frame changes.",
                change_count=4,
            ),
            ActivityCandidate(
                12.0,
                ActivityType.UNCERTAIN,
                0.30,
                "Isolated visual change.",
            ),
        ),
        sample_interval_seconds=0.5,
        sampled_frame_count=40,
        video_duration_seconds=20.0,
    )
    window._project = Project(name="Timeline Test")
    window._on_activity_ready(result)
    if window._review_dialog is not None:
        window._review_dialog.close()

    assert len(timeline.events) == 2
    first_event = timeline.events[0]
    assert first_event.timestamp_seconds == 4.0
    assert first_event.classification is EventClassification.KEYBOARD_TAP

    # Click the first marker to select it and drag it to 6.0s
    marker_x = timeline.time_to_x(4.0)
    target_x = timeline.time_to_x(6.0)
    track_y = 55.0

    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(marker_x, track_y),
        QPointF(marker_x, track_y),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    timeline.mousePressEvent(press)
    assert timeline.selected_event_id == first_event.event_id
    assert window.workspace_panel.event_inspector.current_event == first_event

    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(target_x, track_y),
        QPointF(target_x, track_y),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    timeline.mouseMoveEvent(move)
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(target_x, track_y),
        QPointF(target_x, track_y),
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    timeline.mouseReleaseEvent(release)

    moved_event = timeline.selected_event()
    assert moved_event is not None
    assert abs(moved_event.timestamp_seconds - 6.0) <= 0.05


def test_event_inspector_add_reclassify_delete_persist_preview_and_export(
    qtbot, tmp_path: Path
) -> None:
    played_Previews: list[bytes] = []
    window = MainWindow()
    window._project_service = ProjectService(tmp_path / "projects")
    window._sound_preview_service = SoundPreviewService(
        window._sound_effects_service,
        player=played_Previews.append,
    )
    window.workspace_panel._preview_service = FakePreviewService()
    output_dir = tmp_path / "output"
    window.output_location.setText(str(output_dir))
    qtbot.addWidget(window)
    window.show()

    video = tmp_path / "coding.mp4"
    video.write_bytes(b"video")
    window._project = Project(
        name="Coding Session",
        source_video=video,
        output_dir=output_dir,
        media_info=MediaInfo(
            path=video,
            duration_seconds=5.0,
            width=1280,
            height=720,
            frame_rate=30.0,
            video_codec="h264",
            audio_codec="aac",
            bit_rate_kbps=1000,
            size_bytes=512,
            audio_streams=("aac",),
        ),
        timeline_events=[
            TimelineEvent(
                event_id="uncertain-1",
                timestamp_seconds=1.0,
                classification=EventClassification.UNCERTAIN,
                enabled=False,
                source=EventSource.DETECTED,
                confidence=0.31,
                evidence="Isolated visual change.",
            )
        ],
    )
    window.project_name.setText("Coding Session")
    window.save_project_button.setEnabled(True)
    window.workspace_panel.set_duration(5.0, load_initial_frame=False)
    window.workspace_panel.set_timeline_events(window._project.timeline_events)

    inspector = window.workspace_panel.event_inspector
    timeline = window.workspace_panel.timeline_widget

    # Select the uncertain event and reclassify it to Mouse Left Click
    timeline.select_event("uncertain-1")
    assert inspector.current_event is not None
    assert not inspector.preview_sound_button.isEnabled()

    inspector.set_classification(EventClassification.MOUSE_LEFT_CLICK)
    reclassified = timeline.selected_event()
    assert reclassified is not None
    assert reclassified.classification is EventClassification.MOUSE_LEFT_CLICK
    assert reclassified.enabled is True
    assert inspector.preview_sound_button.isEnabled()

    # Audition the sound effect and try a variation
    inspector.preview_sound_button.click()
    assert len(played_Previews) == 1
    inspector.audition_variation_button.click()
    assert len(played_Previews) == 2

    # Seek to 2.5s and manually add an event
    window.workspace_panel.seek_to(2.5, user_initiated=False)
    inspector.add_event_button.click()
    assert len(window._project.timeline_events) == 2
    added = timeline.selected_event()
    assert added is not None
    assert added.timestamp_seconds == 2.5
    assert added.source is EventSource.MANUAL

    # Move the manual event via the spinbox to 3.25s
    inspector.timestamp_spin.setValue(3.25)
    assert timeline.selected_event().timestamp_seconds == 3.25

    # Save project and reopen in a second MainWindow instance
    window._save_project()
    assert window._project_file is not None and window._project_file.is_file()

    reopened_window = MainWindow()
    reopened_window._project_service = window._project_service
    reopened_window.workspace_panel._preview_service = FakePreviewService()
    qtbot.addWidget(reopened_window)
    assert reopened_window.load_project(window._project_file)
    qtbot.waitUntil(
        lambda: reopened_window.workspace_panel._frame_worker is None, timeout=2000
    )

    restored_events = reopened_window.workspace_panel.timeline_widget.events
    assert len(restored_events) == 2
    assert [e.timestamp_seconds for e in restored_events] == [1.0, 3.25]
    assert [e.classification for e in restored_events] == [
        EventClassification.MOUSE_LEFT_CLICK,
        EventClassification.KEYBOARD_TAP,
    ]

    # Export timeline WAV from inspector
    reopened_window.output_location.setText(str(output_dir))
    reopened_window.workspace_panel.event_inspector.export_timeline_button.click()
    exported_wavs = list(output_dir.glob("codesound-activity-*.wav"))
    assert len(exported_wavs) == 1
    with wave.open(str(exported_wavs[0]), "rb") as wav_file:
        assert wav_file.getframerate() == 44_100
        assert wav_file.getnframes() >= 5 * 44_100

    # Delete the manual event
    reopened_window.workspace_panel.timeline_widget.select_event(added.event_id)
    reopened_window.workspace_panel.event_inspector.delete_event_button.click()
    assert len(reopened_window.workspace_panel.timeline_widget.events) == 1


def test_reanalysis_preserves_manual_and_edited_events_and_supports_mix_preview(
    qtbot, tmp_path: Path
) -> None:
    played: list[bytes] = []
    stopped: list[bool] = []
    window = MainWindow()
    window._sound_preview_service = SoundPreviewService(
        window._sound_effects_service,
        player=played.append,
        stopper=lambda: stopped.append(True),
    )
    window.workspace_panel._preview_service = FakePreviewService()
    qtbot.addWidget(window)
    window.show()

    window._project = Project(name="Preserve Edits")
    window.workspace_panel.set_duration(10.0, load_initial_frame=False)

    # User adds a manual event at 2.0s
    window.workspace_panel.seek_to(2.0, user_initiated=False)
    window.workspace_panel.event_inspector.add_event_button.click()
    manual_id = window.workspace_panel.timeline_widget.selected_event_id
    assert manual_id is not None

    # Run activity analysis with a typing burst at 4.0s, 4.5s
    result = ActivityAnalysisResult(
        candidates=(
            ActivityCandidate(
                4.0,
                ActivityType.TYPING,
                0.55,
                "2 nearby localized frame changes.",
                change_count=2,
                event_timestamps=(4.0, 4.5),
            ),
        ),
        sample_interval_seconds=0.5,
        sampled_frame_count=20,
        video_duration_seconds=10.0,
    )
    window._on_activity_ready(result)
    assert window._review_dialog is not None
    window._review_dialog.apply_button.click()

    events = window.workspace_panel.timeline_widget.events
    assert [e.timestamp_seconds for e in events] == [2.0, 4.0, 4.5]
    assert events[0].event_id == manual_id

    # Edit the detected event at 4.0s -> becomes user_edited=True
    window.workspace_panel.timeline_widget.select_event(events[1].event_id)
    window.workspace_panel.event_inspector.set_classification(
        EventClassification.MOUSE_LEFT_CLICK
    )

    # Re-run analysis with a new detection at 7.0s -> manual (2.0s) and edited (4.0s) survive!
    result_2 = ActivityAnalysisResult(
        candidates=(
            ActivityCandidate(
                7.0,
                ActivityType.TYPING,
                0.52,
                "2 nearby localized frame changes.",
                change_count=2,
                event_timestamps=(7.0, 7.5),
            ),
        ),
        sample_interval_seconds=0.5,
        sampled_frame_count=20,
        video_duration_seconds=10.0,
    )
    window._on_activity_ready(result_2)
    if window._review_dialog is not None:
        window._review_dialog.close()

    after_reanalysis = window.workspace_panel.timeline_widget.events
    assert [e.timestamp_seconds for e in after_reanalysis] == [2.0, 4.0, 7.0, 7.5]
    assert after_reanalysis[1].classification is EventClassification.MOUSE_LEFT_CLICK

    # Preview full timeline mix and stop audio
    window.workspace_panel.event_inspector.preview_mix_button.click()
    assert len(played) == 1
    window.workspace_panel.event_inspector.stop_preview_button.click()
    assert stopped == [True]
