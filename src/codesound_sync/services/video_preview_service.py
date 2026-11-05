"""Local FFmpeg-backed video frame extraction and preview streaming service."""

from __future__ import annotations

import logging
import math
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from codesound_sync.config import FFPROBE_TIMEOUT_SECONDS
from codesound_sync.services.ffmpeg_service import (
    FFmpegNotFoundError,
    get_ffmpeg_path,
)

log = logging.getLogger(__name__)

PREVIEW_FRAME_WIDTH = 640
PREVIEW_FRAME_HEIGHT = 360
PREVIEW_DEFAULT_FPS = 15.0


class VideoPreviewError(RuntimeError):
    """Raised when FFmpeg cannot decode video frames for preview."""


@dataclass(frozen=True)
class PreviewFrame:
    """A single decoded RGB24 preview frame at a source-video timestamp."""

    timestamp_seconds: float
    width: int
    height: int
    rgb_bytes: bytes

    def __post_init__(self) -> None:
        if (
            isinstance(self.timestamp_seconds, bool)
            or not isinstance(self.timestamp_seconds, (int, float))
            or not math.isfinite(self.timestamp_seconds)
            or self.timestamp_seconds < 0
        ):
            raise ValueError("Frame timestamp must be a finite, non-negative number.")
        if (
            isinstance(self.width, bool)
            or not isinstance(self.width, int)
            or self.width < 1
            or isinstance(self.height, bool)
            or not isinstance(self.height, int)
            or self.height < 1
        ):
            raise ValueError("Frame width and height must be positive integers.")
        expected_len = self.width * self.height * 3
        if not isinstance(self.rgb_bytes, bytes) or len(self.rgb_bytes) != expected_len:
            raise ValueError(
                f"Expected {expected_len} RGB24 bytes for a {self.width}x{self.height} frame."
            )


def format_timestamp(seconds: float | None, *, include_centiseconds: bool = True) -> str:
    """Format a timestamp in seconds as MM:SS.cc (or HH:MM:SS.cc if >= 1 hour)."""
    if (
        seconds is None
        or isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        return "00:00.00" if include_centiseconds else "00:00"

    total_centiseconds = round(float(seconds) * 100)
    total_seconds, centiseconds = divmod(total_centiseconds, 100)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        base = f"{minutes:02d}:{secs:02d}"
    return f"{base}.{centiseconds:02d}" if include_centiseconds else base


class VideoPreviewService:
    """Decode single frames or continuous RGB24 preview streams using local FFmpeg."""

    def __init__(
        self,
        frame_width: int = PREVIEW_FRAME_WIDTH,
        frame_height: int = PREVIEW_FRAME_HEIGHT,
        preview_fps: float = PREVIEW_DEFAULT_FPS,
    ) -> None:
        if (
            isinstance(frame_width, bool)
            or not isinstance(frame_width, int)
            or frame_width < 16
            or isinstance(frame_height, bool)
            or not isinstance(frame_height, int)
            or frame_height < 16
        ):
            raise ValueError("Preview dimensions must be integers >= 16.")
        if (
            isinstance(preview_fps, bool)
            or not isinstance(preview_fps, (int, float))
            or not math.isfinite(preview_fps)
            or not 1.0 <= preview_fps <= 60.0
        ):
            raise ValueError("Preview FPS must be between 1 and 60.")

        self.frame_width = frame_width
        self.frame_height = frame_height
        self.preview_fps = float(preview_fps)

    @property
    def frame_byte_size(self) -> int:
        return self.frame_width * self.frame_height * 3

    def extract_frame(
        self,
        video_path: Path,
        timestamp_seconds: float = 0.0,
    ) -> PreviewFrame:
        """Decode one RGB24 frame at *timestamp_seconds*."""
        video_path = Path(video_path)
        if not video_path.is_file():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if (
            isinstance(timestamp_seconds, bool)
            or not isinstance(timestamp_seconds, (int, float))
            or not math.isfinite(timestamp_seconds)
            or timestamp_seconds < 0
        ):
            raise ValueError("Seek timestamp must be a finite, non-negative number.")

        ffmpeg = get_ffmpeg_path()
        target_ts = float(timestamp_seconds)
        raw_bytes = self._run_single_frame_ffmpeg(ffmpeg, video_path, target_ts)

        # Seeking right to the container duration can land past the final video PTS.
        if not raw_bytes and target_ts > 0.0:
            fallback_ts = max(0.0, target_ts - 0.1)
            raw_bytes = self._run_single_frame_ffmpeg(ffmpeg, video_path, fallback_ts)
            if not raw_bytes and fallback_ts > 0.0:
                raw_bytes = self._run_single_frame_ffmpeg(ffmpeg, video_path, 0.0)

        if len(raw_bytes) != self.frame_byte_size:
            raise VideoPreviewError(
                "FFmpeg did not return a complete video frame for preview."
            )

        return PreviewFrame(
            timestamp_seconds=target_ts,
            width=self.frame_width,
            height=self.frame_height,
            rgb_bytes=raw_bytes,
        )

    def _run_single_frame_ffmpeg(
        self,
        ffmpeg: Path,
        video_path: Path,
        timestamp_seconds: float,
    ) -> bytes:
        filter_expr = (
            f"scale={self.frame_width}:{self.frame_height}:flags=bilinear,"
            "format=rgb24"
        )
        cmd = [
            str(ffmpeg),
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{timestamp_seconds:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            filter_expr,
            "-an",
            "-sn",
            "-dn",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=FFPROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise VideoPreviewError(
                f"FFmpeg frame extraction timed out after {FFPROBE_TIMEOUT_SECONDS}s."
            ) from exc
        except OSError as exc:
            raise VideoPreviewError(f"Could not launch FFmpeg: {exc}") from exc

        if result.returncode != 0:
            stderr_text = (
                result.stderr.decode("utf-8", errors="replace").strip()[:300]
                if isinstance(result.stderr, (bytes, bytearray))
                else ""
            )
            details = stderr_text or "The video codec or file may be unsupported."
            raise VideoPreviewError(
                f"FFmpeg could not decode preview frame: {details}"
            )
        return bytes(result.stdout or b"")

    def stream_frames(
        self,
        video_path: Path,
        start_seconds: float = 0.0,
        *,
        fps: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[PreviewFrame]:
        """Stream sequential RGB24 frames starting at *start_seconds*."""
        video_path = Path(video_path)
        if not video_path.is_file():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if (
            isinstance(start_seconds, bool)
            or not isinstance(start_seconds, (int, float))
            or not math.isfinite(start_seconds)
            or start_seconds < 0
        ):
            raise ValueError("Start timestamp must be a finite, non-negative number.")

        stream_fps = float(fps) if fps is not None else self.preview_fps
        if (
            isinstance(fps, bool)
            or not math.isfinite(stream_fps)
            or not 1.0 <= stream_fps <= 60.0
        ):
            raise ValueError("Stream FPS must be between 1 and 60.")

        ffmpeg = get_ffmpeg_path()
        filter_expr = (
            f"fps={stream_fps:.6f},"
            f"scale={self.frame_width}:{self.frame_height}:flags=bilinear,"
            "format=rgb24"
        )
        cmd = [
            str(ffmpeg),
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{float(start_seconds):.3f}",
            "-i",
            str(video_path),
            "-vf",
            filter_expr,
            "-an",
            "-sn",
            "-dn",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        process: subprocess.Popen[bytes] | None = None
        frame_size = self.frame_byte_size
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if process.stdout is None:
                raise VideoPreviewError("FFmpeg did not provide a video frame stream.")

            frame_index = 0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return
                chunk = process.stdout.read(frame_size)
                if not chunk:
                    break
                if len(chunk) != frame_size:
                    if cancel_event is not None and cancel_event.is_set():
                        return
                    raise VideoPreviewError("FFmpeg returned an incomplete preview frame.")
                timestamp = float(start_seconds) + (frame_index / stream_fps)
                frame_index += 1
                yield PreviewFrame(
                    timestamp_seconds=timestamp,
                    width=self.frame_width,
                    height=self.frame_height,
                    rgb_bytes=chunk,
                )

            return_code = process.wait()
            if cancel_event is not None and cancel_event.is_set():
                return
            if return_code != 0:
                raise VideoPreviewError(
                    "FFmpeg could not decode the video stream for playback."
                )
        except OSError as exc:
            raise VideoPreviewError(
                f"Could not run FFmpeg for video playback: {exc}"
            ) from exc
        finally:
            if process is not None:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    process.wait()
                if process.stdout is not None:
                    process.stdout.close()
