"""Local heuristic analysis of sampled video frames for visual activity."""

from __future__ import annotations

import logging
import math
import subprocess
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from codesound_sync.models.activity_candidate import (
    ActivityAnalysisResult,
    ActivityCandidate,
    ActivityType,
)
from codesound_sync.services.ffmpeg_service import (
    FFmpegNotFoundError,
    MediaProbeError,
    get_ffmpeg_path,
    probe_media,
)

log = logging.getLogger(__name__)

ANALYSIS_FRAME_WIDTH = 160
ANALYSIS_FRAME_HEIGHT = 90
_PROGRESS_FRAME_INTERVAL = 24


class ActivityAnalysisError(RuntimeError):
    """Raised when a video cannot be sampled for activity analysis."""


class ActivityAnalysisCancelled(RuntimeError):
    """Raised when the user cancels activity analysis."""


@dataclass(frozen=True)
class _FrameChange:
    timestamp_seconds: float
    changed_fraction: float
    changed_row_fraction: float
    is_widespread: bool


class FrameActivityAnalyzer:
    """Detect changes in downsampled grayscale frames, not definite input.

    Video decoding and frame-rate sampling use the existing local FFmpeg tools.
    Persistent frame differences are clustered as possible typing-like activity;
    isolated differences are kept as uncertain activity. Visual frames alone are
    not used to claim mouse-button clicks.
    """

    def __init__(
        self,
        sample_interval_seconds: float = 0.5,
        pixel_delta_threshold: int = 28,
        changed_pixel_fraction: float = 0.004,
        typing_cluster_gap_seconds: float = 1.0,
        widespread_pixel_fraction: float = 0.25,
        widespread_row_fraction: float = 0.40,
    ) -> None:
        if (
            isinstance(sample_interval_seconds, bool)
            or not isinstance(sample_interval_seconds, (int, float))
            or not math.isfinite(sample_interval_seconds)
            or not 0.05 <= sample_interval_seconds <= 60.0
        ):
            raise ValueError("Sample interval must be between 0.05 and 60 seconds.")
        if (
            isinstance(pixel_delta_threshold, bool)
            or not isinstance(pixel_delta_threshold, int)
            or not 1 <= pixel_delta_threshold <= 255
        ):
            raise ValueError("Pixel threshold must be an integer from 1 to 255.")
        if (
            isinstance(changed_pixel_fraction, bool)
            or not isinstance(changed_pixel_fraction, (int, float))
            or not math.isfinite(changed_pixel_fraction)
            or not 0.0 < changed_pixel_fraction <= 1.0
        ):
            raise ValueError("Changed-pixel threshold must be between 0 and 1.")
        if (
            isinstance(typing_cluster_gap_seconds, bool)
            or not isinstance(typing_cluster_gap_seconds, (int, float))
            or not math.isfinite(typing_cluster_gap_seconds)
            or typing_cluster_gap_seconds <= 0
        ):
            raise ValueError("Activity cluster gap must be greater than zero.")
        if (
            isinstance(widespread_pixel_fraction, bool)
            or not isinstance(widespread_pixel_fraction, (int, float))
            or not math.isfinite(widespread_pixel_fraction)
            or not 0.0 < widespread_pixel_fraction <= 1.0
        ):
            raise ValueError("Widespread-pixel threshold must be between 0 and 1.")
        if (
            isinstance(widespread_row_fraction, bool)
            or not isinstance(widespread_row_fraction, (int, float))
            or not math.isfinite(widespread_row_fraction)
            or not 0.0 < widespread_row_fraction <= 1.0
        ):
            raise ValueError("Widespread-row threshold must be between 0 and 1.")

        self.sample_interval_seconds = float(sample_interval_seconds)
        self.pixel_delta_threshold = pixel_delta_threshold
        self.changed_pixel_fraction = float(changed_pixel_fraction)
        self.typing_cluster_gap_seconds = float(typing_cluster_gap_seconds)
        self.widespread_pixel_fraction = float(widespread_pixel_fraction)
        self.widespread_row_fraction = float(widespread_row_fraction)

    def analyze_frames(
        self,
        frames: Iterable[bytes],
        *,
        frame_width: int = ANALYSIS_FRAME_WIDTH,
        frame_height: int = ANALYSIS_FRAME_HEIGHT,
        video_duration_seconds: float | None = None,
        cancel_event: threading.Event | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ActivityAnalysisResult:
        """Analyze grayscale frames at configured intervals (frame zero at t=0)."""
        if (
            isinstance(frame_width, bool)
            or not isinstance(frame_width, int)
            or frame_width < 1
            or isinstance(frame_height, bool)
            or not isinstance(frame_height, int)
            or frame_height < 1
        ):
            raise ValueError("Frame dimensions must be positive integers.")
        frame_size = frame_width * frame_height
        previous: bytes | None = None
        changes: list[_FrameChange] = []
        sampled_frames = 0

        for frame_index, frame in enumerate(frames):
            if cancel_event is not None and cancel_event.is_set():
                raise ActivityAnalysisCancelled("Activity analysis was cancelled.")
            if not isinstance(frame, bytes) or len(frame) != frame_size:
                raise ActivityAnalysisError(
                    f"Expected a {frame_width}x{frame_height} grayscale frame."
                )
            timestamp = frame_index * self.sample_interval_seconds
            sampled_frames += 1
            if previous is not None:
                changed_fraction, changed_row_fraction = self._measure_frame_change(
                    previous,
                    frame,
                    frame_width=frame_width,
                    frame_height=frame_height,
                )
                if changed_fraction >= self.changed_pixel_fraction:
                    is_widespread = (
                        changed_fraction >= self.widespread_pixel_fraction
                        or changed_row_fraction >= self.widespread_row_fraction
                    )
                    changes.append(
                        _FrameChange(
                            timestamp_seconds=timestamp,
                            changed_fraction=changed_fraction,
                            changed_row_fraction=changed_row_fraction,
                            is_widespread=is_widespread,
                        )
                    )
            previous = frame

            if (
                progress_callback is not None
                and sampled_frames % _PROGRESS_FRAME_INTERVAL == 0
            ):
                progress_callback(
                    f"Compared {sampled_frames} sampled frames "
                    f"(through {timestamp:.1f} seconds)."
                )

        candidates = self._group_changes(changes)
        duration = (
            float(video_duration_seconds)
            if video_duration_seconds is not None
            else max(0.0, (sampled_frames - 1) * self.sample_interval_seconds)
        )
        return ActivityAnalysisResult(
            candidates=tuple(candidates),
            sample_interval_seconds=self.sample_interval_seconds,
            sampled_frame_count=sampled_frames,
            video_duration_seconds=duration,
        )

    def analyze_video(
        self,
        video_path: Path,
        *,
        cancel_event: threading.Event | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ActivityAnalysisResult:
        """Decode a local video to small grayscale frames and analyze changes."""
        video_path = Path(video_path)
        if not video_path.is_file():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if cancel_event is not None and cancel_event.is_set():
            raise ActivityAnalysisCancelled("Activity analysis was cancelled.")

        try:
            media_info = probe_media(video_path)
            ffmpeg = get_ffmpeg_path()
        except (FFmpegNotFoundError, MediaProbeError, FileNotFoundError):
            raise

        rate_filter = 1.0 / self.sample_interval_seconds
        filter_expression = (
            f"fps={rate_filter:.8f},"
            f"scale={ANALYSIS_FRAME_WIDTH}:{ANALYSIS_FRAME_HEIGHT}:flags=area,"
            "format=gray"
        )
        command = [
            str(ffmpeg),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-vf",
            filter_expression,
            "-an",
            "-sn",
            "-dn",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ]
        log.info("Sampling video frames for activity analysis: %s", video_path.name)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            frames = self._read_frames(
                process,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            result = self.analyze_frames(
                frames,
                video_duration_seconds=media_info.duration_seconds,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            return_code = process.wait()
            if cancel_event is not None and cancel_event.is_set():
                raise ActivityAnalysisCancelled("Activity analysis was cancelled.")
            if return_code != 0:
                raise ActivityAnalysisError(
                    "FFmpeg could not decode the video for activity analysis."
                )
            return result
        except OSError as exc:
            raise ActivityAnalysisError(
                f"Could not run FFmpeg for activity analysis: {exc}"
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

    def _read_frames(
        self,
        process: subprocess.Popen[bytes],
        *,
        cancel_event: threading.Event | None,
        progress_callback: Callable[[str], None] | None,
    ) -> Iterator[bytes]:
        if process.stdout is None:
            raise ActivityAnalysisError("FFmpeg did not provide a frame stream.")

        frame_size = ANALYSIS_FRAME_WIDTH * ANALYSIS_FRAME_HEIGHT
        frame_number = 0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ActivityAnalysisCancelled("Activity analysis was cancelled.")
            frame = process.stdout.read(frame_size)
            if not frame:
                break
            if len(frame) != frame_size:
                raise ActivityAnalysisError("FFmpeg returned an incomplete video frame.")
            frame_number += 1
            if (
                progress_callback is not None
                and frame_number % _PROGRESS_FRAME_INTERVAL == 0
            ):
                timestamp = frame_number * self.sample_interval_seconds
                progress_callback(
                    f"Sampled {frame_number} frames (through {timestamp:.1f} seconds)."
                )
            yield frame

    def _measure_frame_change(
        self,
        previous: bytes,
        current: bytes,
        *,
        frame_width: int,
        frame_height: int,
    ) -> tuple[float, float]:
        """Compute changed pixel fraction and fraction of rows with changed pixels."""
        prev_view = memoryview(previous)
        curr_view = memoryview(current)
        threshold = self.pixel_delta_threshold
        frame_size = frame_width * frame_height
        changed_pixels = 0
        changed_rows = 0

        for row_start in range(0, frame_size, frame_width):
            row_end = row_start + frame_width
            row_changed = sum(
                1
                for old_pixel, new_pixel in zip(
                    prev_view[row_start:row_end], curr_view[row_start:row_end]
                )
                if abs(new_pixel - old_pixel) >= threshold
            )
            if row_changed:
                changed_pixels += row_changed
                changed_rows += 1

        return changed_pixels / frame_size, changed_rows / frame_height

    def _group_changes(
        self, changes: list[_FrameChange]
    ) -> list[ActivityCandidate]:
        groups: list[list[_FrameChange]] = []
        for change in changes:
            if (
                not groups
                or groups[-1][-1].is_widespread != change.is_widespread
                or change.timestamp_seconds - groups[-1][-1].timestamp_seconds
                > self.typing_cluster_gap_seconds
            ):
                groups.append([change])
            else:
                groups[-1].append(change)

        candidates: list[ActivityCandidate] = []
        for group in groups:
            count = len(group)
            timestamps = tuple(change.timestamp_seconds for change in group)
            timestamp = timestamps[0]
            if group[0].is_widespread:
                peak_fraction = max(change.changed_fraction for change in group)
                confidence = min(0.32, 0.18 + peak_fraction * 0.2)
                candidate_type = ActivityType.UNCERTAIN
                if count == 1:
                    evidence = (
                        "Widespread visual change across the frame; likely a scene "
                        "cut, window switch, or scrolling rather than localized typing."
                    )
                else:
                    evidence = (
                        f"{count} widespread visual changes across the frame; likely "
                        "scrolling, scene cuts, or full-screen animation rather than "
                        "localized typing."
                    )
            elif count >= 2:
                confidence = min(0.62, 0.40 + 0.035 * min(count - 2, 6))
                candidate_type = ActivityType.TYPING
                evidence = (
                    f"{count} nearby localized frame changes; possible typing, "
                    "animation, or other visual activity. Not proof of keypresses."
                )
            else:
                confidence = min(0.38, 0.22 + group[0].changed_fraction * 0.8)
                candidate_type = ActivityType.UNCERTAIN
                evidence = (
                    "One isolated localized visual change; could be cursor blink, "
                    "animation, or interaction."
                )
            candidates.append(
                ActivityCandidate(
                    timestamp_seconds=timestamp,
                    candidate_type=candidate_type,
                    confidence=confidence,
                    evidence=evidence,
                    change_count=count,
                    event_timestamps=timestamps,
                )
            )
        return candidates
