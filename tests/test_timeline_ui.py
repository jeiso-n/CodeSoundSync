from __future__ import annotations

import wave
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

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
from codesound_sync.services.sound_generator import KeyboardSoundStyle, MouseSoundStyle
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
    window.video_preview._preview_service = fake_preview
    qtbot.addWidget(window)
    window.show()

    media_info = MediaInfo(
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
    )
    window._project = Project(
        name="Demo",
        source_video=video,
        media_info=media_info,
    )
    window.video_step.show_loaded_video(video, media_info=media_info)
    window.video_preview.set_video(video)
    window.video_preview.set_duration(10.0, load_initial_frame=True)
    window.review_step.timeline_widget.set_duration(10.0)
    qtbot.waitUntil(
        lambda: window.video_preview._frame_worker is None, timeout=2000
    )

    assert fake_preview.extracted_timestamps == [0.0]
    assert window.video_preview._current_pixmap is not None
    assert window.video_preview.time_label.text() == "00:00.00 / 00:10.00"

    window.video_preview.step_forward_button.click()
    qtbot.waitUntil(
        lambda: window.video_preview._frame_worker is None, timeout=2000
    )
    assert window.video_preview.current_seconds == 0.25
    assert window.review_step.timeline_widget.playhead_seconds == 0.25

    window.video_preview.step_back_button.click()
    qtbot.waitUntil(
        lambda: window.video_preview._frame_worker is None, timeout=2000
    )
    assert window.video_preview.current_seconds == 0.0

    window.video_preview.play_pause_button.click()
    qtbot.waitUntil(
        lambda: window.video_preview._frame_worker is None, timeout=3000
    )
    assert window.video_preview.play_pause_button.text() == "Play"
    assert window.video_preview.current_seconds == 10.0

    fake_preview.should_fail = True
    window.video_preview.play_pause_button.click()
    qtbot.waitUntil(
        lambda: window.video_preview._frame_worker is None, timeout=2000
    )
    assert "Video preview could not play" in window.friendly_status_label.text()


def test_timeline_coordinate_mapping_filtering_and_mouse_drag_editing(
    qtbot, tmp_path: Path
) -> None:
    window = MainWindow()
    window.video_preview._preview_service = FakePreviewService()
    qtbot.addWidget(window)
    window.resize(1100, 720)
    window.show()
    window._switch_step(1)

    timeline = window.review_step.timeline_widget
    timeline.resize(600, 96)
    window.video_preview.set_duration(20.0, load_initial_frame=False)
    timeline.set_duration(20.0)

    mid_x = timeline.time_to_x(10.0)
    assert abs(timeline.x_to_time(mid_x) - 10.0) <= 0.05

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

    assert len(timeline.events) == 2
    assert window.review_step.uncertain_banner.isVisible()
    first_event = timeline.events[0]
    assert first_event.timestamp_seconds == 4.0
    assert first_event.classification is EventClassification.KEYBOARD_TAP

    # Filter pills
    window.review_step.filter_buttons["keyboard"].click()
    assert len(timeline.visible_events()) == 1
    window.review_step.filter_buttons["uncertain"].click()
    assert len(timeline.visible_events()) == 1
    assert timeline.visible_events()[0].classification is EventClassification.UNCERTAIN
    window.review_step.filter_buttons["all"].click()
    assert len(timeline.visible_events()) == 2

    # Click the first marker to select it and drag it to 6.0s
    marker_x = timeline.time_to_x(4.0)
    target_x = timeline.time_to_x(6.0)
    track_y = 55.0

    timeline.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(marker_x, track_y),
            QPointF(marker_x, track_y),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    assert timeline.selected_event_id == first_event.event_id

    timeline.mouseMoveEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(target_x, track_y),
            QPointF(target_x, track_y),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    timeline.mouseReleaseEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(target_x, track_y),
            QPointF(target_x, track_y),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
    )

    moved_event = timeline.selected_event()
    assert moved_event is not None
    assert abs(moved_event.timestamp_seconds - 6.0) <= 0.05


def test_review_sound_customization_persist_and_export_workflow(
    qtbot, tmp_path: Path
) -> None:
    played_previews: list[bytes] = []
    stopped: list[bool] = []
    window = MainWindow()
    window._project_service = ProjectService(tmp_path / "projects")
    window._sound_preview_service = SoundPreviewService(
        window._sound_effects_service,
        player=played_previews.append,
        stopper=lambda: stopped.append(True),
    )
    window.video_preview._preview_service = FakePreviewService()
    output_dir = tmp_path / "output"
    window.export_step.output_location_edit.setText(str(output_dir))
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
    window.export_step.project_name_edit.setText("Coding Session")
    window.save_project_button.setEnabled(True)
    window.video_preview.set_duration(5.0, load_initial_frame=False)
    window.review_step.timeline_widget.set_duration(5.0)
    window._sync_timeline_ui()
    window._switch_step(1)

    timeline = window.review_step.timeline_widget
    timeline.select_event("uncertain-1")
    assert not window.review_step.preview_event_button.isEnabled()

    window.review_step.set_classification(EventClassification.MOUSE_LEFT_CLICK)
    reclassified = timeline.selected_event()
    assert reclassified is not None
    assert reclassified.classification is EventClassification.MOUSE_LEFT_CLICK
    assert reclassified.enabled is True
    assert window.review_step.preview_event_button.isEnabled()

    # Add a manual key tap at 2.5s
    window.video_preview.seek_to(2.5, user_initiated=False)
    window.review_step.add_key_button.click()
    assert len(window._project.timeline_events) == 2

    # Move via spinbox
    window.review_step.timestamp_spin.setValue(3.25)
    assert timeline.selected_event().timestamp_seconds == 3.25

    # Sound tab: apply preset, preview samples & mix
    window._switch_step(2)
    window.sound_step.preset_laptop_button.click()
    profile = window._sound_effects_service.sound_profile
    assert profile.keyboard_style is KeyboardSoundStyle.SOFT_LAPTOP
    assert profile.mouse_style is MouseSoundStyle.SOFT_CLICK
    assert profile.keyboard_volume == 0.7

    window.sound_step.preview_keyboard_button.click()
    window.sound_step.preview_mix_button.click()
    window.sound_step.stop_audio_button.click()
    assert len(played_previews) == 2
    assert stopped == [True]

    # Save and reopen
    window._save_project()
    assert window._project_file is not None and window._project_file.is_file()

    reopened = MainWindow()
    reopened._project_service = window._project_service
    reopened.video_preview._preview_service = FakePreviewService()
    qtbot.addWidget(reopened)
    assert reopened.load_project(window._project_file)
    qtbot.waitUntil(lambda: reopened.video_preview._frame_worker is None, timeout=2000)

    restored_events = reopened.review_step.timeline_widget.events
    assert [e.timestamp_seconds for e in restored_events] == [1.0, 3.25]
    assert [e.classification for e in restored_events] == [
        EventClassification.MOUSE_LEFT_CLICK,
        EventClassification.KEYBOARD_TAP,
    ]

    # Export WAV in Export tab
    reopened._switch_step(3)
    reopened.export_step.output_location_edit.setText(str(output_dir))
    reopened.export_step.export_audio_button.click()
    exported_wavs = list(output_dir.glob("codesound-activity-*.wav"))
    assert len(exported_wavs) == 1
    with wave.open(str(exported_wavs[0]), "rb") as wav_file:
        assert wav_file.getframerate() == 44_100
        assert wav_file.getnframes() >= 5 * 44_100
    assert "Audio exported successfully" in reopened.friendly_status_label.text()


def test_reanalysis_preserves_manual_and_edited_events(
    qtbot, tmp_path: Path
) -> None:
    window = MainWindow()
    window.video_preview._preview_service = FakePreviewService()
    qtbot.addWidget(window)
    window.show()

    window._project = Project(name="Preserve Edits")
    window.video_preview.set_duration(10.0, load_initial_frame=False)
    window.review_step.timeline_widget.set_duration(10.0)

    # User adds a manual event at 2.0s
    window.video_preview.seek_to(2.0, user_initiated=False)
    window.review_step.add_key_button.click()
    manual_id = window.review_step.timeline_widget.selected_event_id
    assert manual_id is not None

    # Detection #1
    result_1 = ActivityAnalysisResult(
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
    window._on_activity_ready(result_1)
    events = window.review_step.timeline_widget.events
    assert [e.timestamp_seconds for e in events] == [2.0, 4.0, 4.5]

    # Edit detected event at 4.0s
    window.review_step.timeline_widget.select_event(events[1].event_id)
    window.review_step.set_classification(EventClassification.MOUSE_LEFT_CLICK)

    # Detection #2 at 7.0s, 7.5s -> manual (2.0s) and edited (4.0s) survive
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
    after = window.review_step.timeline_widget.events
    assert [e.timestamp_seconds for e in after] == [2.0, 4.0, 7.0, 7.5]
    assert after[1].classification is EventClassification.MOUSE_LEFT_CLICK
