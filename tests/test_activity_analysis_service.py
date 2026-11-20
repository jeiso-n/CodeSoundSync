from __future__ import annotations

import io
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from codesound_sync.models.activity_candidate import (
    ActivityAnalysisResult,
    ActivityCandidate,
    ActivityType,
    candidates_to_sound_events,
)
from codesound_sync.models.media_info import MediaInfo
from codesound_sync.models.sound_event import SoundEventType
from codesound_sync.services import activity_analysis_service
from codesound_sync.services.activity_analysis_service import (
    ActivityAnalysisCancelled,
    ActivityAnalysisError,
    FrameActivityAnalyzer,
)


def _frame(*changed_pixels: int, size: int = 100) -> bytes:
    pixels = bytearray(size)
    for pixel in changed_pixels:
        pixels[pixel] = 255
    return bytes(pixels)


def _analyzer() -> FrameActivityAnalyzer:
    return FrameActivityAnalyzer(
        sample_interval_seconds=0.5,
        pixel_delta_threshold=20,
        changed_pixel_fraction=0.02,
        typing_cluster_gap_seconds=0.75,
    )


def test_frame_samples_use_configured_interval_and_cluster_nearby_changes() -> None:
    analyzer = _analyzer()
    frames = [
        _frame(),
        _frame(*range(10)),
        _frame(*range(20)),
        _frame(*range(30)),
    ]

    result = analyzer.analyze_frames(
        frames,
        frame_width=10,
        frame_height=10,
        video_duration_seconds=2.0,
    )

    assert result.sampled_frame_count == 4
    assert result.sample_interval_seconds == 0.5
    assert result.video_duration_seconds == 2.0
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.timestamp_seconds == 0.5
    assert candidate.candidate_type is ActivityType.TYPING
    assert candidate.change_count == 3
    assert 0.0 <= candidate.confidence <= 1.0
    assert "Not proof" in candidate.evidence


def test_isolated_visual_change_stays_uncertain_and_unchanged_frames_are_ignored() -> None:
    analyzer = _analyzer()
    unchanged = _frame()
    stable = analyzer.analyze_frames(
        [unchanged, unchanged, unchanged],
        frame_width=10,
        frame_height=10,
    )
    isolated = analyzer.analyze_frames(
        [unchanged, _frame(*range(10)), _frame(*range(10))],
        frame_width=10,
        frame_height=10,
    )

    assert stable.candidates == ()
    assert len(isolated.candidates) == 1
    assert isolated.candidates[0].timestamp_seconds == 0.5
    assert isolated.candidates[0].candidate_type is ActivityType.UNCERTAIN
    assert isolated.candidates[0].confidence < 0.5


def test_empty_frames_report_no_events_and_keep_known_duration() -> None:
    result = _analyzer().analyze_frames(
        [],
        frame_width=10,
        frame_height=10,
        video_duration_seconds=7.25,
    )
    assert result.candidates == ()
    assert result.sampled_frame_count == 0
    assert result.video_duration_seconds == 7.25


def test_long_gaps_are_deduplicated_into_separate_bursts() -> None:
    analyzer = _analyzer()
    changed = _frame(*range(30))
    frames = [
        _frame(),
        _frame(*range(10)),
        _frame(*range(20)),
        _frame(*range(30)),
        changed,
        changed,
        changed,
        changed,
        _frame(*range(40)),
    ]
    result = analyzer.analyze_frames(frames, frame_width=10, frame_height=10)
    assert [candidate.timestamp_seconds for candidate in result.candidates] == [0.5, 4.0]


def test_invalid_analysis_configuration_and_frame_shape_are_rejected() -> None:
    with pytest.raises(ValueError, match="Sample interval"):
        FrameActivityAnalyzer(sample_interval_seconds=0)
    with pytest.raises(ValueError, match="Pixel threshold"):
        FrameActivityAnalyzer(pixel_delta_threshold=300)
    with pytest.raises(ValueError, match="Changed-pixel"):
        FrameActivityAnalyzer(changed_pixel_fraction=0)
    with pytest.raises(ValueError, match="Widespread-pixel"):
        FrameActivityAnalyzer(widespread_pixel_fraction=0)
    with pytest.raises(ValueError, match="Widespread-row"):
        FrameActivityAnalyzer(widespread_row_fraction=1.5)
    with pytest.raises(ActivityAnalysisError, match="grayscale frame"):
        _analyzer().analyze_frames([b"short"], frame_width=10, frame_height=10)


@pytest.mark.parametrize(
    "candidate_kwargs",
    [
        {"timestamp_seconds": -1},
        {"timestamp_seconds": float("inf")},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"candidate_type": "keystroke"},
        {"evidence": ""},
        {"event_timestamps": (-0.5,)},
        {"event_timestamps": (float("nan"),)},
        {"event_timestamps": (True,)},
        {"event_timestamps": "1.0"},
        {"event_timestamps": None},
    ],
)
def test_activity_candidate_rejects_invalid_fields(candidate_kwargs: dict) -> None:
    values = {
        "timestamp_seconds": 1.0,
        "candidate_type": ActivityType.TYPING,
        "confidence": 0.5,
        "evidence": "Repeated visual changes.",
    }
    values.update(candidate_kwargs)
    with pytest.raises(ValueError):
        ActivityCandidate(**values)


def test_selected_candidate_conversion_maps_supported_and_skips_uncertain() -> None:
    candidates = (
        ActivityCandidate(1.0, ActivityType.TYPING, 0.6, "Typing-like."),
        ActivityCandidate(2.0, ActivityType.LEFT_CLICK, 0.8, "Click evidence."),
        ActivityCandidate(3.0, ActivityType.RIGHT_CLICK, 0.7, "Click evidence."),
        ActivityCandidate(4.0, ActivityType.UNCERTAIN, 0.3, "Visual change."),
    )

    events = candidates_to_sound_events(candidates[:3])

    assert [event.event_type for event in events] == [
        SoundEventType.KEYBOARD_TAP,
        SoundEventType.MOUSE_LEFT_CLICK,
        SoundEventType.MOUSE_RIGHT_CLICK,
    ]
    assert candidates_to_sound_events((candidates[-1],)) == ()


def test_video_sampling_command_uses_ffmpeg_and_preserves_sample_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "synthetic.mp4"
    video.write_bytes(b"synthetic")
    raw_frames = _frame(size=160 * 90) + _frame(
        *range(300), size=160 * 90
    )
    calls: list[tuple[list[str], dict]] = []

    class FakeProcess:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            calls.append((command, kwargs))
            self.stdout = io.BytesIO(raw_frames)

        def wait(self) -> int:
            return 0

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(
        activity_analysis_service,
        "probe_media",
        lambda path: MediaInfo(
            path=path,
            duration_seconds=1.0,
            width=1920,
            height=1080,
            frame_rate=30.0,
            video_codec="h264",
            audio_codec=None,
            bit_rate_kbps=100,
            size_bytes=10,
        ),
    )
    monkeypatch.setattr(
        activity_analysis_service, "get_ffmpeg_path", lambda: Path("ffmpeg.exe")
    )
    monkeypatch.setattr(activity_analysis_service.subprocess, "Popen", FakeProcess)

    result = _analyzer().analyze_video(video)

    command, kwargs = calls[0]
    assert str(video) in command
    assert "fps=2.00000000" in command[command.index("-vf") + 1]
    assert kwargs["stderr"] == activity_analysis_service.subprocess.DEVNULL
    assert result.sampled_frame_count == 2
    assert len(result.candidates) == 1
    assert result.candidates[0].timestamp_seconds == 0.5
    assert result.video_duration_seconds == 1.0


def test_empty_video_frame_stream_returns_no_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "empty.mp4"
    video.write_bytes(b"synthetic empty")

    class EmptyProcess:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.stdout = io.BytesIO()

        def wait(self) -> int:
            return 0

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(
        activity_analysis_service,
        "probe_media",
        lambda path: SimpleNamespace(duration_seconds=0.0),
    )
    monkeypatch.setattr(
        activity_analysis_service, "get_ffmpeg_path", lambda: Path("ffmpeg.exe")
    )
    monkeypatch.setattr(activity_analysis_service.subprocess, "Popen", EmptyProcess)

    result = _analyzer().analyze_video(video)
    assert result.candidates == ()
    assert result.sampled_frame_count == 0


def test_cancellation_and_ffmpeg_errors_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancellation = threading.Event()
    cancellation.set()
    with pytest.raises(ActivityAnalysisCancelled):
        _analyzer().analyze_frames(
            [_frame()],
            frame_width=10,
            frame_height=10,
            cancel_event=cancellation,
        )

    video = tmp_path / "bad.mp4"
    video.write_bytes(b"bad")
    monkeypatch.setattr(
        activity_analysis_service,
        "probe_media",
        lambda path: SimpleNamespace(duration_seconds=1.0),
    )
    monkeypatch.setattr(
        activity_analysis_service, "get_ffmpeg_path", lambda: Path("ffmpeg.exe")
    )

    class FailedProcess:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.stdout = io.BytesIO()

        def wait(self) -> int:
            return 1

        def poll(self) -> int:
            return 1

    monkeypatch.setattr(activity_analysis_service.subprocess, "Popen", FailedProcess)
    with pytest.raises(ActivityAnalysisError, match="could not decode"):
        _analyzer().analyze_video(video)


def test_older_stage_one_project_json_still_loads(tmp_path: Path) -> None:
    from codesound_sync.services.project_service import ProjectService

    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(
        '{"project_id":"old-id","name":"Old Lesson",'
        '"source_video":"lesson.mp4","output_dir":"rendered",'
        '"media_info":null,"created_at":"2025-01-01T00:00:00+00:00",'
        '"modified_at":"2025-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )

    loaded = ProjectService(tmp_path / "projects").load_file(legacy_path)

    assert loaded.project_id == "old-id"
    assert loaded.name == "Old Lesson"
    assert loaded.source_video == Path("lesson.mp4")
    assert loaded.output_dir == Path("rendered")


def _row_pattern_frame(rows: tuple[int, ...], *, cols: tuple[int, ...] = (0, 1)) -> bytes:
    """Create a 10x10 frame with bright pixels at specified (row, col) positions."""
    pixels = bytearray(100)
    for row in rows:
        for col in cols:
            pixels[row * 10 + col] = 255
    return bytes(pixels)


def test_global_scene_cuts_are_classified_as_uncertain_not_typing() -> None:
    analyzer = _analyzer()
    frames = [
        _frame(),
        bytes([255] * 100),  # 100% scene cut
        bytes([0] * 100),    # 100% scene cut back
    ]

    result = analyzer.analyze_frames(frames, frame_width=10, frame_height=10)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.candidate_type is ActivityType.UNCERTAIN
    assert candidate.change_count == 2
    assert candidate.event_timestamps == (0.5, 1.0)
    assert candidate.to_sound_events() == ()
    assert candidate.to_sound_event() is None
    assert candidates_to_sound_events(result.candidates) == ()


def test_broad_scrolling_across_many_rows_is_rejected_as_uncertain() -> None:
    analyzer = _analyzer()
    # Each consecutive frame changes only 12% of pixels (< 25% pixel threshold)
    # but across 6 of 10 rows (60% >= 40% row threshold), simulating vertical scroll.
    frames = [
        _row_pattern_frame((0, 1, 2, 3, 4, 5), cols=(0,)),
        _row_pattern_frame((0, 1, 2, 3, 4, 5), cols=(2,)),
        _row_pattern_frame((0, 1, 2, 3, 4, 5), cols=(4,)),
        _row_pattern_frame((0, 1, 2, 3, 4, 5), cols=(6,)),
    ]

    result = analyzer.analyze_frames(frames, frame_width=10, frame_height=10)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.candidate_type is ActivityType.UNCERTAIN
    assert candidate.change_count == 3
    assert candidate.event_timestamps == (0.5, 1.0, 1.5)
    assert candidates_to_sound_events(result.candidates) == ()


def test_widespread_change_splits_nearby_typing_clusters() -> None:
    analyzer = FrameActivityAnalyzer(
        sample_interval_seconds=0.5,
        pixel_delta_threshold=20,
        changed_pixel_fraction=0.02,
        typing_cluster_gap_seconds=1.5,
    )
    # Typing burst #1 at t=0.5, 1.0 -> scene cut at t=1.5 -> typing burst #2 at t=2.0, 2.5
    base = bytearray(100)
    t1 = bytearray(base)
    t1[0:4] = bytes([255] * 4)
    t2 = bytearray(t1)
    t2[4:8] = bytes([255] * 4)
    cut = bytearray([200] * 100)
    t3 = bytearray(cut)
    t3[0:4] = bytes([0] * 4)
    t4 = bytearray(t3)
    t4[4:8] = bytes([0] * 4)

    result = analyzer.analyze_frames(
        [bytes(base), bytes(t1), bytes(t2), bytes(cut), bytes(t3), bytes(t4)],
        frame_width=10,
        frame_height=10,
    )

    assert [(c.candidate_type, c.event_timestamps) for c in result.candidates] == [
        (ActivityType.TYPING, (0.5, 1.0)),
        (ActivityType.UNCERTAIN, (1.5,)),
        (ActivityType.TYPING, (2.0, 2.5)),
    ]
    events = candidates_to_sound_events(result.candidates)
    assert [event.timestamp_seconds for event in events] == [0.5, 1.0, 2.0, 2.5]
    assert all(event.event_type is SoundEventType.KEYBOARD_TAP for event in events)


def test_widespread_change_prevents_merging_single_localized_changes_across_cut() -> None:
    analyzer = FrameActivityAnalyzer(
        sample_interval_seconds=0.5,
        pixel_delta_threshold=20,
        changed_pixel_fraction=0.02,
        typing_cluster_gap_seconds=1.5,
    )
    base = bytearray(100)
    local_before = bytearray(base)
    local_before[0:5] = bytes([255] * 5)
    cut = bytearray([200] * 100)
    local_after = bytearray(cut)
    local_after[0:5] = bytes([0] * 5)

    result = analyzer.analyze_frames(
        [bytes(base), bytes(local_before), bytes(cut), bytes(local_after)],
        frame_width=10,
        frame_height=10,
    )

    assert len(result.candidates) == 3
    assert all(c.candidate_type is ActivityType.UNCERTAIN for c in result.candidates)
    assert [c.timestamp_seconds for c in result.candidates] == [0.5, 1.0, 1.5]
    assert candidates_to_sound_events(result.candidates) == ()


def test_typing_burst_preserves_exact_multi_tap_cadence_and_sorts_flattened_events() -> None:
    analyzer = _analyzer()
    frames = [
        _frame(),
        _frame(*range(10)),
        _frame(*range(20)),
        _frame(*range(30)),
    ]

    result = analyzer.analyze_frames(frames, frame_width=10, frame_height=10)
    assert len(result.candidates) == 1
    typing_candidate = result.candidates[0]

    assert typing_candidate.candidate_type is ActivityType.TYPING
    assert typing_candidate.event_timestamps == (0.5, 1.0, 1.5)

    burst_events = typing_candidate.to_sound_events()
    assert [event.timestamp_seconds for event in burst_events] == [0.5, 1.0, 1.5]
    assert all(event.event_type is SoundEventType.KEYBOARD_TAP for event in burst_events)
    assert typing_candidate.to_sound_event() == burst_events[0]

    later_burst = ActivityCandidate(
        timestamp_seconds=3.0,
        candidate_type=ActivityType.TYPING,
        confidence=0.55,
        evidence="Later typing burst.",
        change_count=2,
        event_timestamps=(3.5, 3.0),
    )
    click = ActivityCandidate(
        timestamp_seconds=2.0,
        candidate_type=ActivityType.LEFT_CLICK,
        confidence=0.6,
        evidence="Click candidate.",
    )
    uncertain = ActivityCandidate(
        timestamp_seconds=1.25,
        candidate_type=ActivityType.UNCERTAIN,
        confidence=0.25,
        evidence="Uncertain.",
    )

    flattened = candidates_to_sound_events(
        (later_burst, uncertain, typing_candidate, click)
    )
    assert [
        (event.timestamp_seconds, event.event_type) for event in flattened
    ] == [
        (0.5, SoundEventType.KEYBOARD_TAP),
        (1.0, SoundEventType.KEYBOARD_TAP),
        (1.5, SoundEventType.KEYBOARD_TAP),
        (2.0, SoundEventType.MOUSE_LEFT_CLICK),
        (3.0, SoundEventType.KEYBOARD_TAP),
        (3.5, SoundEventType.KEYBOARD_TAP),
    ]


def test_legacy_candidate_construction_defaults_event_timestamps() -> None:
    legacy_typing = ActivityCandidate(
        1.25,
        ActivityType.TYPING,
        0.5,
        "Legacy candidate without event_timestamps.",
        change_count=3,
    )
    legacy_uncertain = ActivityCandidate(
        2.5,
        ActivityType.UNCERTAIN,
        0.3,
        "Legacy uncertain candidate.",
    )

    assert legacy_typing.event_timestamps == (1.25,)
    events = legacy_typing.to_sound_events()
    assert len(events) == 1
    assert events[0].timestamp_seconds == 1.25
    assert events[0].event_type is SoundEventType.KEYBOARD_TAP
    assert legacy_typing.to_sound_event() == events[0]

    assert legacy_uncertain.event_timestamps == (2.5,)
    assert legacy_uncertain.to_sound_events() == ()
    assert legacy_uncertain.to_sound_event() is None
