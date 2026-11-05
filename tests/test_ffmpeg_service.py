from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codesound_sync.services import ffmpeg_service


def _ensure_ffmpeg_on_path(monkeypatch: pytest.MonkeyPatch) -> bool:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
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
            combined = os.pathsep.join(
                [*extra_paths, os.environ.get("PATH", "")]
            )
            monkeypatch.setenv("PATH", combined)
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def test_probe_media_uses_argument_list_and_parses_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "lesson; & sample.mp4"
    video.write_bytes(b"not a real video")
    calls: list[tuple[list[str], dict]] = []

    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", lambda: Path("ffprobe.exe"))

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"format":{"duration":"12","size":"5"},'
                '"streams":[{"codec_type":"video","width":640,"height":360,'
                '"r_frame_rate":"25/1","codec_name":"h264"}]}'
            ),
            stderr="",
        )

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)
    info = ffmpeg_service.probe_media(video)

    command, kwargs = calls[0]
    assert command[1:3] == ["-v", "error"]
    assert command[-2:] == ["-i", str(video)]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert "shell" not in kwargs
    assert info.resolution == "640×360"
    assert info.frame_rate == 25.0


def test_check_ffmpeg_available_uses_utf8_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(ffmpeg_service, "get_ffmpeg_path", lambda: Path("ffmpeg.exe"))
    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", lambda: Path("ffprobe.exe"))

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="ffmpeg version 9.0.1-essentials_build\n",
            stderr="",
        )

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)
    available, version = ffmpeg_service.check_ffmpeg_available()

    assert available is True
    assert version == "ffmpeg version 9.0.1-essentials_build"
    _, kwargs = calls[0]
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"


def test_probe_media_reports_missing_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    def missing_probe() -> Path:
        raise ffmpeg_service.FFmpegNotFoundError(
            "'ffprobe' was not found on PATH. Install FFmpeg and restart the application."
        )

    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", missing_probe)
    with pytest.raises(ffmpeg_service.FFmpegNotFoundError, match="ffprobe.*PATH"):
        ffmpeg_service.probe_media(video)


def test_probe_media_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Video file not found"):
        ffmpeg_service.probe_media(tmp_path / "absent.mp4")


def test_probe_media_reports_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", lambda: Path("ffprobe.exe"))

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("ffprobe", 1)

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", timeout)
    with pytest.raises(ffmpeg_service.MediaProbeError, match="timed out"):
        ffmpeg_service.probe_media(video)


def test_probe_media_explains_unreadable_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "invalid.mp4"
    video.write_bytes(b"not a video")
    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", lambda: Path("ffprobe.exe"))
    monkeypatch.setattr(
        ffmpeg_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr=""
        ),
    )

    with pytest.raises(
        ffmpeg_service.MediaProbeError, match="invalid, unsupported, or unreadable"
    ):
        ffmpeg_service.probe_media(video)


@pytest.mark.parametrize("missing_stdout", [None, "", "   \n\t  "])
def test_probe_media_rejects_missing_or_empty_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_stdout: str | None,
) -> None:
    video = tmp_path / "How To Use Primary Keys In MySQL Workbench 🥶.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", lambda: Path("ffprobe.exe"))
    monkeypatch.setattr(
        ffmpeg_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=missing_stdout, stderr=""
        ),
    )

    with pytest.raises(
        ffmpeg_service.MediaProbeError, match="returned no media metadata output"
    ):
        ffmpeg_service.probe_media(video)


def test_probe_media_rejects_malformed_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "corrupt-json.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", lambda: Path("ffprobe.exe"))
    monkeypatch.setattr(
        ffmpeg_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="{not valid json", stderr=""
        ),
    )

    with pytest.raises(
        ffmpeg_service.MediaProbeError, match="Could not parse ffprobe JSON output"
    ):
        ffmpeg_service.probe_media(video)


def test_probe_media_handles_none_stderr_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "broken.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(ffmpeg_service, "get_ffprobe_path", lambda: Path("ffprobe.exe"))
    monkeypatch.setattr(
        ffmpeg_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout=None, stderr=None
        ),
    )

    with pytest.raises(
        ffmpeg_service.MediaProbeError, match="invalid, unsupported, or unreadable"
    ):
        ffmpeg_service.probe_media(video)


def test_probe_media_extracts_metadata_from_real_video_with_spaces_and_unicode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not _ensure_ffmpeg_on_path(monkeypatch):
        pytest.skip("ffmpeg and ffprobe are required for real media probing test")

    video = (
        tmp_path
        / "How To Use Primary Keys In MySQL Workbench \U0001f976 \U0001f433.mp4"
    )
    ffmpeg = ffmpeg_service.get_ffmpeg_path()
    subprocess.run(
        [
            str(ffmpeg),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1280x720:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-metadata",
            "title=MySQL Primary Keys \U0001f976 \U0001f433 \u201d \ufe0f \u200d \U0001f601",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    info = ffmpeg_service.probe_media(video)

    assert info.path == video
    assert info.width == 1280
    assert info.height == 720
    assert info.resolution == "1280×720"
    assert info.frame_rate == 30.0
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert info.audio_streams == ("aac",)
    assert info.duration_seconds is not None and info.duration_seconds >= 0.9
    assert info.size_bytes > 0
