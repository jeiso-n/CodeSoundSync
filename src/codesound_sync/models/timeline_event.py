"""Editable timeline sound events bridging detected candidates and synthesis."""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from codesound_sync.models.activity_candidate import ActivityCandidate, ActivityType
from codesound_sync.models.sound_event import SoundEvent, SoundEventType


class EventClassification(str, Enum):
    """Editable event classification on the project timeline."""

    KEYBOARD_TAP = "keyboard_tap"
    MOUSE_LEFT_CLICK = "mouse_left_click"
    MOUSE_RIGHT_CLICK = "mouse_right_click"
    UNCERTAIN = "uncertain"

    @property
    def label(self) -> str:
        return {
            EventClassification.KEYBOARD_TAP: "Keyboard Tap",
            EventClassification.MOUSE_LEFT_CLICK: "Mouse Left Click",
            EventClassification.MOUSE_RIGHT_CLICK: "Mouse Right Click",
            EventClassification.UNCERTAIN: "Uncertain Activity",
        }[self]


class EventSource(str, Enum):
    """Origin of a timeline event."""

    DETECTED = "detected"
    MANUAL = "manual"


_CANDIDATE_CLASSIFICATION_MAP: dict[ActivityType, EventClassification] = {
    ActivityType.TYPING: EventClassification.KEYBOARD_TAP,
    ActivityType.LEFT_CLICK: EventClassification.MOUSE_LEFT_CLICK,
    ActivityType.RIGHT_CLICK: EventClassification.MOUSE_RIGHT_CLICK,
    ActivityType.UNCERTAIN: EventClassification.UNCERTAIN,
}


@dataclass(frozen=True)
class TimelineEvent:
    """An editable event marker on the video timeline."""

    timestamp_seconds: float
    classification: EventClassification = EventClassification.KEYBOARD_TAP
    enabled: bool = True
    source: EventSource = EventSource.MANUAL
    confidence: float | None = None
    evidence: str = ""
    intensity: float = 0.7
    variation: float = 0.0
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if (
            isinstance(self.timestamp_seconds, bool)
            or not isinstance(self.timestamp_seconds, (int, float))
            or not math.isfinite(self.timestamp_seconds)
            or self.timestamp_seconds < 0
        ):
            raise ValueError("Timeline event timestamp must be finite and non-negative.")
        object.__setattr__(self, "timestamp_seconds", float(self.timestamp_seconds))

        try:
            classification = EventClassification(self.classification)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Unsupported timeline event classification: {self.classification!r}."
            ) from exc
        object.__setattr__(self, "classification", classification)

        if not isinstance(self.enabled, bool):
            raise ValueError("Timeline event enabled flag must be a boolean.")

        try:
            source = EventSource(self.source)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Unsupported timeline event source: {self.source!r}."
            ) from exc
        object.__setattr__(self, "source", source)

        if self.confidence is not None:
            if (
                isinstance(self.confidence, bool)
                or not isinstance(self.confidence, (int, float))
                or not math.isfinite(self.confidence)
                or not 0.0 <= self.confidence <= 1.0
            ):
                raise ValueError("Timeline event confidence must be between 0 and 1 or None.")
            object.__setattr__(self, "confidence", float(self.confidence))

        if not isinstance(self.evidence, str):
            raise ValueError("Timeline event evidence must be a string.")

        if (
            isinstance(self.intensity, bool)
            or not isinstance(self.intensity, (int, float))
            or not math.isfinite(self.intensity)
            or not 0.0 <= self.intensity <= 1.0
        ):
            raise ValueError("Timeline event intensity must be between 0 and 1.")
        object.__setattr__(self, "intensity", float(self.intensity))

        if (
            isinstance(self.variation, bool)
            or not isinstance(self.variation, (int, float))
            or not math.isfinite(self.variation)
            or not -1.0 <= self.variation <= 1.0
        ):
            raise ValueError("Timeline event variation must be between -1 and 1.")
        object.__setattr__(self, "variation", float(self.variation))

        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("Timeline event ID must be a non-empty string.")

    @property
    def is_renderable(self) -> bool:
        """Return True when this event is enabled and has a concrete sound type."""
        return self.enabled and self.classification is not EventClassification.UNCERTAIN

    def to_sound_event(self) -> SoundEvent | None:
        """Convert to a renderable SoundEvent, or None if disabled/uncertain."""
        if not self.is_renderable:
            return None
        return SoundEvent(
            timestamp_seconds=self.timestamp_seconds,
            event_type=SoundEventType(self.classification.value),
            intensity=self.intensity,
            variation=self.variation,
        )

    @classmethod
    def from_candidate(
        cls,
        candidate: ActivityCandidate,
        *,
        enabled: bool | None = None,
    ) -> "TimelineEvent":
        """Create a detected TimelineEvent from an ActivityCandidate."""
        if not isinstance(candidate, ActivityCandidate):
            raise ValueError("Expected an ActivityCandidate instance.")
        classification = _CANDIDATE_CLASSIFICATION_MAP[candidate.candidate_type]
        is_enabled = (
            classification is not EventClassification.UNCERTAIN
            if enabled is None
            else bool(enabled)
        )
        intensity = round(min(0.7, max(0.25, float(candidate.confidence))), 4)
        return cls(
            timestamp_seconds=candidate.timestamp_seconds,
            classification=classification,
            enabled=is_enabled,
            source=EventSource.DETECTED,
            confidence=candidate.confidence,
            evidence=candidate.evidence,
            intensity=intensity,
            variation=0.0,
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp_seconds": self.timestamp_seconds,
            "classification": self.classification.value,
            "enabled": self.enabled,
            "source": self.source.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "intensity": self.intensity,
            "variation": self.variation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimelineEvent":
        if not isinstance(data, dict):
            raise ValueError("Timeline event data must be a JSON object.")
        if "timestamp_seconds" not in data or "classification" not in data:
            raise ValueError("Timeline event requires timestamp_seconds and classification.")
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            timestamp_seconds=data["timestamp_seconds"],
            classification=EventClassification(data["classification"]),
            enabled=data.get("enabled", True),
            source=EventSource(data.get("source", EventSource.MANUAL.value)),
            confidence=data.get("confidence"),
            evidence=data.get("evidence", ""),
            intensity=data.get("intensity", 0.7),
            variation=data.get("variation", 0.0),
        )


def timeline_events_to_sound_events(
    events: Iterable[TimelineEvent],
) -> tuple[SoundEvent, ...]:
    """Convert enabled, concrete TimelineEvents to sorted SoundEvents."""
    ordered = sorted(events, key=lambda item: (item.timestamp_seconds, item.event_id))
    rendered: list[SoundEvent] = []
    for item in ordered:
        sound_event = item.to_sound_event()
        if sound_event is not None:
            rendered.append(sound_event)
    return tuple(rendered)


def candidates_to_timeline_events(
    candidates: Iterable[ActivityCandidate],
    *,
    selected_candidates: Iterable[ActivityCandidate] | None = None,
) -> list[TimelineEvent]:
    """Convert ActivityCandidates into TimelineEvents, preserving selection state."""
    selected_set = set(selected_candidates) if selected_candidates is not None else None
    result: list[TimelineEvent] = []
    for candidate in candidates:
        enabled = (
            candidate in selected_set
            if selected_set is not None
            else (candidate.to_sound_event() is not None)
        )
        result.append(TimelineEvent.from_candidate(candidate, enabled=enabled))
    result.sort(key=lambda item: (item.timestamp_seconds, item.event_id))
    return result
