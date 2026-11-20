"""Non-blocking local sound-effect auditioning service."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable

from codesound_sync.models.sound_event import SoundEvent
from codesound_sync.models.timeline_event import (
    EventClassification,
    TimelineEvent,
    timeline_events_to_sound_events,
)
from codesound_sync.services.sound_effects_service import SoundEffectsService

log = logging.getLogger(__name__)


class SoundPreviewError(RuntimeError):
    """Raised when a sound effect cannot be auditioned."""


def _default_play_wav_bytes(wav_bytes: bytes) -> None:
    if sys.platform == "win32":
        import winsound

        try:
            winsound.PlaySound(
                wav_bytes,
                winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except RuntimeError as exc:
            raise SoundPreviewError(
                f"Audio output device could not play preview: {exc}"
            ) from exc


def _default_stop_audio() -> None:
    if sys.platform == "win32":
        import winsound

        try:
            winsound.PlaySound(None, 0)
        except RuntimeError:
            pass


class SoundPreviewService:
    """Synthesize and audition single sound effects or timeline mixes without blocking."""

    def __init__(
        self,
        effects_service: SoundEffectsService | None = None,
        player: Callable[[bytes], None] | None = None,
        stopper: Callable[[], None] | None = None,
    ) -> None:
        self._effects_service = effects_service or SoundEffectsService()
        self._player = player or _default_play_wav_bytes
        self._stopper = stopper or _default_stop_audio
        self._active_buffer: bytes | None = None

    @property
    def last_wav_bytes(self) -> bytes | None:
        """Keep a reference to the latest in-memory WAV buffer for SND_MEMORY."""
        return self._active_buffer

    def stop(self) -> None:
        """Stop any currently playing preview audio."""
        self._stopper()

    def preview_sound_event(self, event: SoundEvent) -> bytes:
        """Synthesize *event* and play it asynchronously, returning the WAV bytes."""
        if not isinstance(event, SoundEvent):
            raise ValueError("Expected a SoundEvent to preview.")
        wav_bytes = self._effects_service.render_event_wav_bytes(event)
        self._active_buffer = wav_bytes
        self._player(wav_bytes)
        return wav_bytes

    def preview_timeline_event(
        self,
        event: TimelineEvent,
        *,
        variation_override: float | None = None,
    ) -> bytes:
        """Audition a TimelineEvent even if it is currently disabled on the track."""
        if not isinstance(event, TimelineEvent):
            raise ValueError("Expected a TimelineEvent to preview.")
        if event.classification is EventClassification.UNCERTAIN:
            raise SoundPreviewError(
                "Uncertain activity has no sound effect until reclassified."
            )
        variation = (
            event.variation
            if variation_override is None
            else float(variation_override)
        )
        sound_event = SoundEvent(
            timestamp_seconds=0.0,
            event_type=event.classification.value,
            intensity=event.intensity,
            variation=variation,
        )
        return self.preview_sound_event(sound_event)

    def preview_timeline_mix(
        self,
        events: Iterable[TimelineEvent],
        *,
        duration_seconds: float | None = None,
        variation: bool = True,
    ) -> bytes:
        """Render included timeline events to an in-memory WAV mix and play it."""
        sound_events = timeline_events_to_sound_events(events)
        if not sound_events:
            raise SoundPreviewError(
                "No included sound events to preview. Add or enable events first."
            )
        wav_bytes = self._effects_service.render_wav_bytes(
            sound_events,
            duration_seconds=duration_seconds,
            variation=variation,
        )
        self._active_buffer = wav_bytes
        self._player(wav_bytes)
        return wav_bytes
