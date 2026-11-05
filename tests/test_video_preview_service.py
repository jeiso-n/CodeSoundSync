from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from codesound_sync.services import video_preview_service
from codesound_sync.services.video_preview_service import (
    PreviewFrame,
    VideoPreviewError,
    VideoPreviewService,
    format_timestamp,
)
from codesound_sync.ui.workers.video_frame_worker import VideoFrameWorker


def _ensure_ffmpeg_on_path(monkeypatch: pytest.MonkeyPatch) -> bool:
    if shutil.which("ffmpeg"):
        return True
    if sys.platform == "win32":
        import winreg

        extra_paths: list[str] = []
        for root, subkey in (
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ),
        ):
            try:
                with winreg.OpenKey(root, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "Path")
                    if isinstance(val, str):
                        extra_paths.append(os.path.expandvars(val))
            except OSError:
                continue
        if extra_paths:
            monkeypatch.setenv(
                "PATH", os.pathsep.join([*extra_paths, os.environ.get("PATH", "")])
            )
    return bool(shutil.which("ffmpeg"))


def test_format_timestamp_handles_subsecond_and_hour_ranges() -> None:
    assert format_timestamp(None) == "00:00.00"
    assert format_timestamp(-1.0) == "00:00.00"
    assert format_timestamp(0.0) == "00:00.00"
    assert format_timestamp(65.432) == "01:05.43"
    assert format_timestamp(3661.5, include_centiseconds=False) == "01:01:01"


def test_preview_frame_validates_dimensions_and_byte_count() -> None:
    frame = PreviewFrame(1.25, 16, 16, bytes(16 * 16 * 3))
    assert frame.timestamp_seconds == 1.25
    with pytest.raises(ValueError, match="RGB24 bytes"):
        PreviewFrame(0.0, 16, 16, b"short")
    with pytest.raises(ValueError, match="timestamp"):
        PreviewFrame(-0.1, 16, 16, bytes(16 * 16 * 3))


def test_extract_frame_builds_ffmpeg_command_and_falls_back_near_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    service = VideoPreviewService(frame_width=32, frame_height=18, preview_fps=10.0)
    expected_bytes = bytes([128]) * service.frame_byte_size
    calls: list[list[str]] = []

    monkeypatch.setattr(
        video_preview_service, "get_ffmpeg_path", lambda: Path("ffmpeg.exe")
    )

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        # First call at EOF returns empty stdout; fallback call succeeds.
        if len(calls) == 1:
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=expected_bytes, stderr=b"")

    monkeypatch.setattr(video_preview_service.subprocess, "run", fake_run)
    frame = service.extract_frame(video, timestamp_seconds=5.0)

    assert len(calls) == 2
    assert calls[0][calls[0].index("-ss") + 1] == "5.000"
    assert calls[1][calls[1].index("-ss") + 1] == "4.900"
    assert frame.timestamp_seconds == 5.0
    assert frame.rgb_bytes == expected_bytes


def test_extract_frame_reports_missing_file_and_codec_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = VideoPreviewService(frame_width=32, frame_height=18)
    with pytest.raises(FileNotFoundError):
        service.extract_frame(tmp_path / "missing.mp4")

    video = tmp_path / "corrupt.mp4"
    video.write_bytes(b"corrupt")
    monkeypatch.setattr(
        video_preview_service, "get_ffmpeg_path", lambda: Path("ffmpeg.exe")
    )
    monkeypatch.setattr(
        video_preview_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"Invalid data found"
        ),
    )
    with pytest.raises(VideoPreviewError, match="Invalid data found"):
        service.extract_frame(video, 0.5)


def test_stream_frames_yields_timed_frames_and_respects_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "stream.mp4"
    video.write_bytes(b"video")
    service = VideoPreviewService(frame_width=16, frame_height=16, preview_fps=10.0)
    raw = bytes(service.frame_byte_size * 3)

    class FakeProcess:
        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            self.stdout = io.BytesIO(raw)

        def wait(self) -> int:
            return 0

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(
        video_preview_service, "get_ffmpeg_path", lambda: Path("ffmpeg.exe")
    )
    monkeypatch.setattr(video_preview_service.subprocess, "Popen", FakeProcess)

    frames = list(service.stream_frames(video, start_seconds=2.0))
    assert [round(f.timestamp_seconds, 2) for f in frames] == [2.0, 2.1, 2.2]

    cancel = threading.Event()
    cancel.set()
    assert list(service.stream_frames(video, start_seconds=0.0, cancel_event=cancel)) == []


def test_video_frame_worker_emits_frame_in_seek_mode(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "worker.mp4"
    video.write_bytes(b"video")
    service = VideoPreviewService(frame_width=16, frame_height=16)
    expected = PreviewFrame(0.75, 16, 16, bytes(16 * 16 * 3))
    monkeypatch.setattr(service, "extract_frame", lambda path, ts: expected)

    worker = VideoFrameWorker(video, mode="seek", timestamp_seconds=0.75, service=service)
    received: list[PreviewFrame] = []
    worker.frame_ready.connect(received.append)
    worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=2000)

    assert received == [expected]


def test_real_ffmpeg_frame_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not _ensure_ffmpeg_on_path(monkeypatch):
        pytest.skip("ffmpeg is required for real frame extraction test")

    video = tmp_path / "preview_test.mp4"
    ffmpeg = video_preview_service.get_ffmpeg_path()
    subprocess.run(
        [
            str(ffmpeg),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=15:d=1",
            "-c:v",
            "libx264",
            str(video),
        ],
        check=True,
        capture_output=True,
    )

    service = VideoPreviewService(frame_width=64, frame_height=36)
    frame = service.extract_frame(video, timestamp_seconds=0.2)
    assert frame.width == 64
    assert frame.height == 36
    assert len(frame.rgb_bytes) == 64 * 36 * 3
