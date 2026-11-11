"""Central workstation panel with video frame preview, playback transport, and timeline."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from codesound_sync.models.timeline_event import TimelineEvent
from codesound_sync.services.video_preview_service import (
    PreviewFrame,
    VideoPreviewService,
    format_timestamp,
)
from codesound_sync.ui.panels.event_inspector_panel import EventInspectorPanel
from codesound_sync.ui.panels.timeline_widget import TimelineWidget
from codesound_sync.ui.workers.video_frame_worker import VideoFrameWorker

_SLIDER_RESOLUTION = 1000
_STEP_SECONDS = 0.25


class WorkspacePanel(QWidget):
    """Video preview canvas, playback controls, timeline, and event inspector."""

    playback_error = Signal(str)
    position_changed = Signal(float)

    def __init__(
        self,
        preview_service: VideoPreviewService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("workspacePanel")
        self._preview_service = preview_service or VideoPreviewService()
        self._video_path: Path | None = None
        self._video_missing: bool = False
        self._duration_seconds: float = 0.0
        self._current_seconds: float = 0.0
        self._current_pixmap: QPixmap | None = None
        self._frame_worker: VideoFrameWorker | None = None
        self._worker_user_initiated: bool = False
        self._pending_seek: tuple[float, bool] | None = None
        self._updating_slider: bool = False

        self._build_ui()
        self._update_transport_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Video frame display / placeholder
        self._preview = QLabel("Import a video to begin")
        self._preview.setObjectName("previewPlaceholder")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumHeight(220)
        self._preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._preview, 1)

        # Playback transport controls
        transport = QHBoxLayout()
        transport.setSpacing(8)

        self.play_pause_button = QPushButton("Play")
        self.play_pause_button.setFixedWidth(72)
        self.play_pause_button.clicked.connect(self.toggle_playback)
        transport.addWidget(self.play_pause_button)

        self.step_back_button = QPushButton("◀ -0.25s")
        self.step_back_button.setToolTip("Step backward 0.25 seconds.")
        self.step_back_button.clicked.connect(
            lambda: self.seek_to(self._current_seconds - _STEP_SECONDS, user_initiated=True)
        )
        transport.addWidget(self.step_back_button)

        self.step_forward_button = QPushButton("+0.25s ▶")
        self.step_forward_button.setToolTip("Step forward 0.25 seconds.")
        self.step_forward_button.clicked.connect(
            lambda: self.seek_to(self._current_seconds + _STEP_SECONDS, user_initiated=True)
        )
        transport.addWidget(self.step_forward_button)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, _SLIDER_RESOLUTION)
        self.seek_slider.valueChanged.connect(self._on_slider_value_changed)
        transport.addWidget(self.seek_slider, 1)

        self.time_label = QLabel("00:00.00 / 00:00.00")
        self.time_label.setObjectName("infoValue")
        self.time_label.setMinimumWidth(135)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        transport.addWidget(self.time_label)
        layout.addLayout(transport)

        # Interactive timeline ruler and event track
        self.timeline_widget = TimelineWidget()
        self.timeline_widget.seek_requested.connect(
            lambda ts: self.seek_to(ts, user_initiated=True)
        )
        layout.addWidget(self.timeline_widget)

        # Event inspector controls
        self.event_inspector = EventInspectorPanel()
        layout.addWidget(self.event_inspector)

        # Selected media path label
        self._path = QLabel("No video selected")
        self._path.setObjectName("selectedMediaPath")
        self._path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._path.setWordWrap(True)
        layout.addWidget(self._path)

    # ------------------------------------------------------------------
    # Public state & lifecycle
    # ------------------------------------------------------------------

    @property
    def current_seconds(self) -> float:
        return self._current_seconds

    @property
    def duration_seconds(self) -> float:
        return self._duration_seconds

    @property
    def is_playing(self) -> bool:
        return (
            self._frame_worker is not None
            and self._frame_worker.isRunning()
            and self._frame_worker.mode == "play"
        )

    def set_video(self, path: Path) -> None:
        self.stop_playback()
        self._video_path = Path(path)
        self._video_missing = False
        self._current_pixmap = None
        self._current_seconds = 0.0
        self._preview.setPixmap(QPixmap())
        self._preview.setText(
            f"Video selected\n\n{path.name}\n\n"
            "Inspecting media metadata…"
        )
        self._path.setText(str(path))
        self.timeline_widget.set_playhead(0.0)
        self._update_time_display()
        self._update_transport_state()

    def set_missing_video(self, path: Path) -> None:
        self.stop_playback()
        self._video_path = Path(path)
        self._video_missing = True
        self._current_pixmap = None
        self._current_seconds = 0.0
        self._preview.setPixmap(QPixmap())
        self._preview.setText(
            f"Source video missing\n\n{path.name}\n\n"
            "The saved project information is still available."
        )
        self._path.setText(str(path))
        self.timeline_widget.set_playhead(0.0)
        self._update_time_display()
        self._update_transport_state()

    def clear(self) -> None:
        self.stop_playback()
        self._video_path = None
        self._video_missing = False
        self._duration_seconds = 0.0
        self._current_seconds = 0.0
        self._current_pixmap = None
        self._preview.setPixmap(QPixmap())
        self._preview.setText("Import a video to begin")
        self._path.setText("No video selected")
        self.timeline_widget.set_duration(0.0)
        self.timeline_widget.set_events(())
        self.timeline_widget.set_playhead(0.0)
        self.event_inspector.set_event(None)
        self._update_time_display()
        self._update_transport_state()

    def set_duration(
        self,
        duration_seconds: float | None,
        *,
        load_initial_frame: bool = True,
    ) -> None:
        self._duration_seconds = (
            float(duration_seconds)
            if duration_seconds is not None and duration_seconds > 0
            else 0.0
        )
        self.timeline_widget.set_duration(self._duration_seconds)
        self.event_inspector.set_max_timestamp(self.timeline_widget.effective_duration)
        self._update_time_display()
        self._update_transport_state()
        if (
            load_initial_frame
            and self._video_path is not None
            and not self._video_missing
            and self._video_path.is_file()
        ):
            self._request_frame_seek(0.0, user_initiated=False)

    def set_timeline_events(
        self,
        events: Iterable[TimelineEvent],
        *,
        selected_event_id: str | None = None,
    ) -> None:
        self.timeline_widget.set_events(events, selected_event_id=selected_event_id)
        self.event_inspector.set_max_timestamp(self.timeline_widget.effective_duration)
        self.event_inspector.set_event(self.timeline_widget.selected_event())
        self._update_time_display()
        self._update_transport_state()

    # ------------------------------------------------------------------
    # Playback & Seeking
    # ------------------------------------------------------------------

    def toggle_playback(self) -> None:
        if self.is_playing:
            self.stop_playback()
        else:
            self.start_playback()

    def start_playback(self) -> None:
        if self._video_path is None or self._video_missing or not self._video_path.is_file():
            self.playback_error.emit("Cannot play: source video file is unavailable.")
            return

        self.stop_playback()
        span = self.timeline_widget.effective_duration
        start_at = self._current_seconds
        if span > 0 and start_at >= span - 0.05:
            start_at = 0.0
            self._set_position_internal(0.0)

        worker = VideoFrameWorker(
            self._video_path,
            mode="play",
            timestamp_seconds=start_at,
            service=self._preview_service,
            parent=self,
        )
        self._frame_worker = worker
        self._worker_user_initiated = True
        self._pending_seek = None
        worker.frame_ready.connect(self._on_frame_ready)
        worker.playback_finished.connect(self._on_playback_finished)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self.play_pause_button.setText("Pause")
        worker.start()

    def stop_playback(self) -> None:
        self._pending_seek = None
        worker = self._frame_worker
        if worker is not None:
            self._frame_worker = None
            worker.cancel()
            # Do not destroy the owning QWidget while its child QThread is running.
            # FFmpeg operations have a bounded timeout, so this wait will finish.
            worker.wait()
            worker.deleteLater()
        self.play_pause_button.setText("Play")

    def shutdown(self) -> None:
        """Stop and wait for any active frame worker before widget destruction."""
        self.stop_playback()

    def seek_to(self, timestamp_seconds: float, *, user_initiated: bool = False) -> None:
        if self.is_playing:
            self.stop_playback()
        span = self.timeline_widget.effective_duration
        clamped = max(0.0, float(timestamp_seconds))
        if span > 0:
            clamped = min(clamped, span)
        self._set_position_internal(clamped)
        if (
            self._video_path is not None
            and not self._video_missing
            and self._video_path.is_file()
        ):
            self._request_frame_seek(clamped, user_initiated=user_initiated)

    def _request_frame_seek(
        self,
        timestamp_seconds: float,
        *,
        user_initiated: bool,
    ) -> None:
        if self._video_path is None:
            return
        if self._frame_worker is not None and self._frame_worker.isRunning():
            # Coalesce rapid seeks while one frame decode is already in flight
            self._pending_seek = (timestamp_seconds, user_initiated)
            return

        worker = VideoFrameWorker(
            self._video_path,
            mode="seek",
            timestamp_seconds=timestamp_seconds,
            service=self._preview_service,
            parent=self,
        )
        self._frame_worker = worker
        self._worker_user_initiated = user_initiated
        worker.frame_ready.connect(self._on_frame_ready)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _set_position_internal(self, seconds: float) -> None:
        self._current_seconds = round(max(0.0, float(seconds)), 3)
        self.timeline_widget.set_playhead(self._current_seconds)
        self._update_time_display()
        self.position_changed.emit(self._current_seconds)

    def _update_time_display(self) -> None:
        span = self.timeline_widget.effective_duration
        self.time_label.setText(
            f"{format_timestamp(self._current_seconds)} / {format_timestamp(span)}"
        )
        self._updating_slider = True
        try:
            if span > 0:
                ratio = max(0.0, min(1.0, self._current_seconds / span))
                self.seek_slider.setValue(round(ratio * _SLIDER_RESOLUTION))
            else:
                self.seek_slider.setValue(0)
        finally:
            self._updating_slider = False

    def _update_transport_state(self) -> None:
        has_playable_video = (
            self._video_path is not None
            and not self._video_missing
            and self._video_path.is_file()
        )
        span = self.timeline_widget.effective_duration
        can_seek = has_playable_video or span > 0.0
        self.play_pause_button.setEnabled(has_playable_video)
        self.step_back_button.setEnabled(can_seek)
        self.step_forward_button.setEnabled(can_seek)
        self.seek_slider.setEnabled(can_seek and span > 0.0)

    def _on_slider_value_changed(self, value: int) -> None:
        if self._updating_slider:
            return
        span = self.timeline_widget.effective_duration
        if span <= 0.0:
            return
        target = (float(value) / _SLIDER_RESOLUTION) * span
        self.seek_to(target, user_initiated=True)

    def _on_frame_ready(self, frame: PreviewFrame) -> None:
        image = QImage(
            frame.rgb_bytes,
            frame.width,
            frame.height,
            frame.width * 3,
            QImage.Format_RGB888,
        ).copy()
        self._current_pixmap = QPixmap.fromImage(image)
        self._render_current_pixmap()
        if self.is_playing:
            span = self.timeline_widget.effective_duration
            ts = min(frame.timestamp_seconds, span) if span > 0 else frame.timestamp_seconds
            self._set_position_internal(ts)

    def _render_current_pixmap(self) -> None:
        if self._current_pixmap is None or self._current_pixmap.isNull():
            return
        target_size = self._preview.size()
        if target_size.width() > 8 and target_size.height() > 8:
            scaled = self._current_pixmap.scaled(
                target_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._preview.setPixmap(scaled)
        else:
            self._preview.setPixmap(self._current_pixmap)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._current_pixmap is not None:
            self._render_current_pixmap()

    def _on_playback_finished(self) -> None:
        self.play_pause_button.setText("Play")
        span = self.timeline_widget.effective_duration
        if span > 0:
            self._set_position_internal(span)

    def _on_worker_error(self, message: str) -> None:
        self.play_pause_button.setText("Play")
        if self._worker_user_initiated:
            if self._current_pixmap is None and self._video_path is not None:
                self._preview.setText(
                    f"Preview unavailable for {self._video_path.name}\n\n{message}"
                )
            self.playback_error.emit(message)
        elif self._current_pixmap is None and self._video_path is not None:
            self._preview.setText(
                f"Video selected\n\n{self._video_path.name}\n\n"
                "Frame preview is ready once valid video streams are decoded."
            )

    def _on_worker_finished(self, worker: VideoFrameWorker) -> None:
        if self._frame_worker is worker:
            self._frame_worker = None
        worker.deleteLater()
        if self._pending_seek is not None and not self.is_playing:
            next_ts, user_init = self._pending_seek
            self._pending_seek = None
            self._request_frame_seek(next_ts, user_initiated=user_init)
