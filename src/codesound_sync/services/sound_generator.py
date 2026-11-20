"""Small deterministic synthetic sound effects for keyboard and mouse events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import random

from codesound_sync.config import AUDIO_SAMPLE_RATE
from codesound_sync.models.sound_event import SoundEventType


class KeyboardSoundStyle(str, Enum):
    """Selectable keyboard synthesis profiles."""

    MECHANICAL_CRISP = "mechanical_crisp"
    SOFT_LAPTOP = "soft_laptop"
    WARM_STUDIO = "warm_studio"

    @property
    def label(self) -> str:
        return {
            KeyboardSoundStyle.MECHANICAL_CRISP: "Crisp Mechanical",
            KeyboardSoundStyle.SOFT_LAPTOP: "Soft Laptop",
            KeyboardSoundStyle.WARM_STUDIO: "Warm Studio",
        }[self]

    @property
    def description(self) -> str:
        return {
            KeyboardSoundStyle.MECHANICAL_CRISP: "Bright, tactile keystrokes with clear switch snap.",
            KeyboardSoundStyle.SOFT_LAPTOP: "Gentle, low-profile scissor-switch taps for subtle background audio.",
            KeyboardSoundStyle.WARM_STUDIO: "Deeper, rounded keycap thock suited for voiceover tutorials.",
        }[self]


class MouseSoundStyle(str, Enum):
    """Selectable mouse-click synthesis profiles."""

    CRISP_SWITCH = "crisp_switch"
    SOFT_CLICK = "soft_click"

    @property
    def label(self) -> str:
        return {
            MouseSoundStyle.CRISP_SWITCH: "Crisp Switch",
            MouseSoundStyle.SOFT_CLICK: "Soft Click",
        }[self]

    @property
    def description(self) -> str:
        return {
            MouseSoundStyle.CRISP_SWITCH: "Defined micro-switch press and release transient.",
            MouseSoundStyle.SOFT_CLICK: "Softer, dampened click that blends lightly under narration.",
        }[self]


@dataclass(frozen=True)
class SoundProfile:
    """User-facing sound customization settings."""

    keyboard_style: KeyboardSoundStyle = KeyboardSoundStyle.MECHANICAL_CRISP
    mouse_style: MouseSoundStyle = MouseSoundStyle.CRISP_SWITCH
    keyboard_volume: float = 1.0
    mouse_volume: float = 1.0
    human_variation: bool = True


class SoundGenerator:
    """Generate short, local effects without third-party audio assets."""

    def __init__(
        self,
        sample_rate: int = AUDIO_SAMPLE_RATE,
        profile: SoundProfile | None = None,
    ) -> None:
        if (
            isinstance(sample_rate, bool)
            or not isinstance(sample_rate, int)
            or not 8_000 <= sample_rate <= 192_000
        ):
            raise ValueError("Sample rate must be an integer from 8000 to 192000 Hz.")
        self.sample_rate = sample_rate
        self.profile = profile or SoundProfile()

    def generate(
        self,
        event_type: SoundEventType,
        intensity: float = 1.0,
        variation: float = 0.0,
        profile: SoundProfile | None = None,
    ) -> list[float]:
        """Synthesize one event as normalized floating-point mono samples."""
        try:
            event_type = SoundEventType(event_type)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Unsupported sound event type: {event_type!r}.") from exc

        if (
            isinstance(intensity, bool)
            or not isinstance(intensity, (int, float))
            or not math.isfinite(intensity)
            or not 0.0 <= intensity <= 1.0
        ):
            raise ValueError("Event intensity must be a finite number from 0 to 1.")
        if (
            isinstance(variation, bool)
            or not isinstance(variation, (int, float))
            or not math.isfinite(variation)
            or not -1.0 <= variation <= 1.0
        ):
            raise ValueError("Event variation must be a finite number from -1 to 1.")

        active_profile = profile or self.profile

        if event_type is SoundEventType.KEYBOARD_TAP:
            duration = 0.048 * (1.0 + 0.14 * variation)
            body_freq = 240.0 * (1.0 + 0.12 * variation)
            click_freq = 2_250.0 * (1.0 + 0.10 * variation)
            body_decay = 0.011
            click_decay = 0.0045
            noise_mix = 0.42
            second_tap_delay = None
            volume_scale = active_profile.keyboard_volume
            if active_profile.keyboard_style is KeyboardSoundStyle.SOFT_LAPTOP:
                duration *= 0.85
                body_freq *= 0.85
                click_freq *= 0.72
                click_decay = 0.0032
                noise_mix = 0.25
            elif active_profile.keyboard_style is KeyboardSoundStyle.WARM_STUDIO:
                duration *= 1.08
                body_freq *= 0.76
                click_freq *= 0.68
                body_decay = 0.014
                noise_mix = 0.30
        elif event_type is SoundEventType.MOUSE_LEFT_CLICK:
            duration = 0.060
            body_freq = 320.0 * (1.0 + 0.08 * variation)
            click_freq = 1_550.0 * (1.0 + 0.08 * variation)
            body_decay = 0.010
            click_decay = 0.004
            noise_mix = 0.48
            second_tap_delay = 0.016
            volume_scale = active_profile.mouse_volume
            if active_profile.mouse_style is MouseSoundStyle.SOFT_CLICK:
                click_freq *= 0.72
                noise_mix = 0.24
                click_decay = 0.0032
        else:
            duration = 0.072
            body_freq = 210.0 * (1.0 + 0.08 * variation)
            click_freq = 1_050.0 * (1.0 + 0.08 * variation)
            body_decay = 0.014
            click_decay = 0.0055
            noise_mix = 0.44
            second_tap_delay = 0.020
            volume_scale = active_profile.mouse_volume
            if active_profile.mouse_style is MouseSoundStyle.SOFT_CLICK:
                click_freq *= 0.75
                noise_mix = 0.24
                click_decay = 0.0042

        rng = random.Random(
            f"{event_type.value}:{round(float(variation), 4)}"
        )
        frame_count = max(1, round(duration * self.sample_rate))
        samples: list[float] = []
        peak = 0.0
        prev_noise = 0.0
        for frame in range(frame_count):
            t = frame / self.sample_rate
            raw_noise = rng.uniform(-1.0, 1.0)
            # High-pass emphasize the noise transient so it sounds crisp, not muddy
            crisp_noise = 0.5 * (raw_noise - prev_noise)
            prev_noise = raw_noise

            attack = 1.0 - math.exp(-t * 2_400.0)
            body = math.sin(2.0 * math.pi * body_freq * t) * math.exp(-t / body_decay)
            click = (
                math.sin(2.0 * math.pi * click_freq * t)
                + 0.35 * math.sin(2.0 * math.pi * (click_freq * 1.62) * t)
            ) * math.exp(-t / click_decay)
            transient = crisp_noise * math.exp(-t / (click_decay * 0.9))

            sample = attack * (0.45 * body + 0.55 * click + noise_mix * transient)

            if second_tap_delay is not None and t >= second_tap_delay:
                t2 = t - second_tap_delay
                release_attack = 1.0 - math.exp(-t2 * 2_200.0)
                release_click = (
                    math.sin(2.0 * math.pi * (click_freq * 0.85) * t2)
                    * math.exp(-t2 / (click_decay * 0.8))
                )
                release_noise = crisp_noise * math.exp(-t2 / (click_decay * 0.7))
                sample += 0.38 * release_attack * (release_click + 0.4 * release_noise)

            samples.append(sample)
            peak = max(peak, abs(sample))

        if peak == 0.0:
            return samples
        clamped_volume = max(0.0, min(1.0, float(volume_scale)))
        output_gain = 0.28 * float(intensity) * clamped_volume / peak
        return [sample * output_gain for sample in samples]
