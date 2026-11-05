"""Background worker for single-frame seeking and continuous video preview playback."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from codesound_sync.services.ffmpeg_service import FFmpegNotFoundError
from codesound_sync.services.video_preview_service import (
    PreviewFrame,
    VideoPreviewError,
    VideoPreviewService,
)

log = logging.getLogger(__name__)


class VideoFrameWorker(QThread):
    """Run FFmpeg video frame extraction or streaming off the Qt GUI thread."""

    frame_ready = Signal(object)  # PreviewFrame
    playback_finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        video_path: Path,
        *,
        mode: str = "seek",
        timestamp_seconds: float = 0.0,
        service: VideoPreviewService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if mode not in ("seek", "play"):
            raise ValueError("Worker mode must be 'seek' or 'play'.")
        self._video_path = Path(video_path)
        self._mode = mode
        self._timestamp_seconds = max(0.0, float(timestamp_seconds))
        self._service = service or VideoPreviewService()
        self._cancel_event = threading.Event()

    @property
    def mode(self) -> str:
        return self._mode

    def cancel(self) -> None:
        """Signal the worker to stop decoding or streaming frames."""
        self._cancel_event.set()

    def run(self) -> None:  # noqa: D102
        if self._cancel_event.is_set():
            return

        try:
            if self._mode == "seek":
                frame = self._service.extract_frame(
                    self._video_path, self._timestamp_seconds
                )
                if not self._cancel_event.is_set():
                    self.frame_ready.emit(frame)
            else:
                fps = self._service.preview_fps
                start_wall = time.monotonic()
                for index, frame in enumerate(
                    self._service.stream_frames(
                        self._video_path,
                        self._timestamp_seconds,
                        fps=fps,
                        cancel_event=self._cancel_event,
                    )
                ):
                    if self._cancel_event.is_set():
                        return
                    self.frame_ready.emit(frame)
                    target_elapsed = (index + 1) / fps
                    remaining = (start_wall + target_elapsed) - time.monotonic()
                    if remaining > 0.002 and self._cancel_event.wait(remaining):
                        return
                if not self._cancel_event.is_set():
                    self.playback_finished.emit()
        except (FFmpegNotFoundError, VideoPreviewError, FileNotFoundError, ValueError) as exc:
            if not self._cancel_event.is_set():
                log.debug("Video preview worker error (%s): %s", self._mode, exc)
                self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            if not self._cancel_event.is_set():
                log.exception("Unexpected error in VideoFrameWorker")
                self.error.emit(f"Unexpected preview error: {type(exc).__name__}: {exc}")
