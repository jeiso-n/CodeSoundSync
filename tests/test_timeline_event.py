from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from codesound_sync.models.activity_candidate import ActivityCandidate, ActivityType
from codesound_sync.models.project import Project
from codesound_sync.models.sound_event import SoundEvent, SoundEventType
from codesound_sync.models.timeline_event import (
    EventClassification,
    EventSource,
    TimelineEvent,
    candidates_to_timeline_events,
    timeline_events_to_sound_events,
)
from codesound_sync.services.project_service import ProjectService
from codesound_sync.services.sound_preview_service import (
    SoundPreviewError,
    SoundPreviewService,
)


def test_timeline_event_converts_from_candidate_and_to_sound_event() -> None:
    typing_candidate = ActivityCandidate(
        timestamp_seconds=1.25,
        candidate_type=ActivityType.TYPING,
        confidence=0.58,
        evidence="4 nearby frame changes.",
        change_count=4,
    )
    uncertain_candidate = ActivityCandidate(
        timestamp_seconds=2.5,
        candidate_type=ActivityType.UNCERTAIN,
        confidence=0.28,
        evidence="Isolated change.",
    )

    typing_event = TimelineEvent.from_candidate(typing_candidate)
    assert typing_event.classification is EventClassification.KEYBOARD_TAP
    assert typing_event.source is EventSource.DETECTED
    assert typing_event.enabled is True
    assert typing_event.confidence == 0.58
    assert typing_event.to_sound_event() == SoundEvent(
        timestamp_seconds=1.25,
        event_type=SoundEventType.KEYBOARD_TAP,
        intensity=0.58,
        variation=0.0,
    )

    uncertain_event = TimelineEvent.from_candidate(uncertain_candidate)
    assert uncertain_event.classification is EventClassification.UNCERTAIN
    assert uncertain_event.enabled is False
    assert uncertain_event.to_sound_event() is None

    events = candidates_to_timeline_events([uncertain_candidate, typing_candidate])
    assert [e.timestamp_seconds for e in events] == [1.25, 2.5]
    assert len(timeline_events_to_sound_events(events)) == 1


@pytest.mark.parametrize(
    "invalid_kwargs",
    [
        {"timestamp_seconds": -0.1},
        {"timestamp_seconds": float("nan")},
        {"classification": "unknown_type"},
        {"enabled": "yes"},
        {"source": "cloud"},
        {"confidence": 1.2},
        {"intensity": -0.1},
        {"variation": 1.5},
        {"event_id": ""},
    ],
)
def test_timeline_event_rejects_invalid_fields(invalid_kwargs: dict) -> None:
    base = {
        "timestamp_seconds": 1.0,
        "classification": EventClassification.KEYBOARD_TAP,
    }
    base.update(invalid_kwargs)
    with pytest.raises(ValueError):
        TimelineEvent(**base)


def test_project_persists_timeline_events_and_loads_legacy_projects(
    tmp_path: Path,
) -> None:
    service = ProjectService(tmp_path / "projects")
    events = [
        TimelineEvent(
            event_id="evt-1",
            timestamp_seconds=0.8,
            classification=EventClassification.KEYBOARD_TAP,
            enabled=True,
            source=EventSource.DETECTED,
            confidence=0.52,
            evidence="Repeated visual changes.",
            intensity=0.52,
            variation=-0.15,
        ),
        TimelineEvent(
            event_id="evt-2",
            timestamp_seconds=2.4,
            classification=EventClassification.MOUSE_LEFT_CLICK,
            enabled=True,
            source=EventSource.MANUAL,
            confidence=None,
            evidence="Manual click marker",
            intensity=0.8,
            variation=0.0,
        ),
    ]
    project = Project(
        name="Timeline Lesson",
        source_video=tmp_path / "lesson.mp4",
        output_dir=tmp_path / "output",
        timeline_events=events,
    )

    saved_path = service.save(project)
    loaded = service.load_file(saved_path)
    assert loaded.timeline_events == events

    legacy_file = tmp_path / "legacy_stage3.json"
    legacy_file.write_text(
        '{"project_id":"legacy-1","name":"Legacy Project",'
        '"source_video":"video.mp4","output_dir":"out","media_info":null}',
        encoding="utf-8",
    )
    loaded_legacy = service.load_file(legacy_file)
    assert loaded_legacy.timeline_events == []


def test_sound_preview_service_renders_valid_wav_bytes_and_calls_player() -> None:
    played_buffers: list[bytes] = []
    preview = SoundPreviewService(player=played_buffers.append)

    event = TimelineEvent(
        timestamp_seconds=3.2,
        classification=EventClassification.MOUSE_RIGHT_CLICK,
        intensity=0.85,
        variation=0.1,
    )
    wav_bytes = preview.preview_timeline_event(event)

    assert len(played_buffers) == 1
    assert played_buffers[0] == wav_bytes
    assert preview.last_wav_bytes == wav_bytes
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 44_100
        assert wav_file.getnframes() > 0

    uncertain = TimelineEvent(
        timestamp_seconds=1.0,
        classification=EventClassification.UNCERTAIN,
    )
    with pytest.raises(SoundPreviewError, match="reclassified"):
        preview.preview_timeline_event(uncertain)
