"""Interactive video timeline ruler, playhead, and sound-event marker track."""

from __future__ import annotations

import math
from collections.abc import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from codesound_sync.models.timeline_event import EventClassification, TimelineEvent
from codesound_sync.services.video_preview_service import format_timestamp

_LEFT_MARGIN = 28.0
_RIGHT_MARGIN = 28.0
_RULER_HEIGHT = 26.0
_MARKER_HIT_RADIUS_PX = 7.0

_CLASSIFICATION_COLOURS: dict[EventClassification, str] = {
    EventClassification.KEYBOARD_TAP: "#3b82f6",
    EventClassification.MOUSE_LEFT_CLICK: "#22c55e",
    EventClassification.MOUSE_RIGHT_CLICK: "#14b8a6",
    EventClassification.UNCERTAIN: "#f59e0b",
}

_VALID_FILTERS = ("all", "keyboard", "mouse", "uncertain")


class TimelineWidget(QWidget):
    """Painted timeline displaying video duration, playhead, and editable events."""

    seek_requested = Signal(float)
    event_selected = Signal(object)  # TimelineEvent | None
    event_moved = Signal(str, float)  # event_id, timestamp_seconds
    delete_requested = Signal(str)  # event_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("timelineWidget")
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)

        self._duration_seconds: float = 0.0
        self._playhead_seconds: float = 0.0
        self._events: list[TimelineEvent] = []
        self._filter_mode: str = "all"
        self._selected_event_id: str | None = None
        self._dragging_event_id: str | None = None
        self._scrubbing_playhead: bool = False

    # ------------------------------------------------------------------
    # Properties & State
    # ------------------------------------------------------------------

    @property
    def duration_seconds(self) -> float:
        return self._duration_seconds

    @property
    def effective_duration(self) -> float:
        """Return usable timeline span in seconds (at least max event timestamp)."""
        max_event_ts = max(
            (event.timestamp_seconds for event in self._events),
            default=0.0,
        )
        return max(self._duration_seconds, max_event_ts)

    @property
    def playhead_seconds(self) -> float:
        return self._playhead_seconds

    @property
    def events(self) -> tuple[TimelineEvent, ...]:
        return tuple(self._events)

    @property
    def filter_mode(self) -> str:
        return self._filter_mode

    def set_filter(self, mode: str) -> None:
        """Filter visible markers by 'all', 'keyboard', 'mouse', or 'uncertain'."""
        normalized = mode.lower().strip()
        if normalized not in _VALID_FILTERS:
            raise ValueError(f"Unsupported timeline filter: {mode!r}")
        self._filter_mode = normalized
        self.update()

    def visible_events(self) -> list[TimelineEvent]:
        """Return events matching the active filter mode."""
        if self._filter_mode == "all":
            return list(self._events)
        if self._filter_mode == "keyboard":
            return [
                e for e in self._events
                if e.classification is EventClassification.KEYBOARD_TAP
            ]
        if self._filter_mode == "mouse":
            return [
                e for e in self._events
                if e.classification in (
                    EventClassification.MOUSE_LEFT_CLICK,
                    EventClassification.MOUSE_RIGHT_CLICK,
                )
            ]
        return [
            e for e in self._events
            if e.classification is EventClassification.UNCERTAIN
        ]

    @property
    def selected_event_id(self) -> str | None:
        return self._selected_event_id

    def selected_event(self) -> TimelineEvent | None:
        if self._selected_event_id is None:
            return None
        for event in self._events:
            if event.event_id == self._selected_event_id:
                return event
        return None

    def set_duration(self, seconds: float | None) -> None:
        if (
            seconds is None
            or isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            self._duration_seconds = 0.0
        else:
            self._duration_seconds = float(seconds)
        if self.effective_duration > 0:
            self._playhead_seconds = min(
                self._playhead_seconds, self.effective_duration
            )
        self.update()

    def set_playhead(self, seconds: float) -> None:
        """Update playhead position without emitting seek_requested."""
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
        ):
            return
        span = self.effective_duration
        clamped = max(0.0, float(seconds))
        if span > 0:
            clamped = min(clamped, span)
        self._playhead_seconds = round(clamped, 3)
        self.update()

    def set_events(
        self,
        events: Iterable[TimelineEvent],
        *,
        selected_event_id: str | None = None,
    ) -> None:
        self._events = sorted(
            events,
            key=lambda item: (item.timestamp_seconds, item.event_id),
        )
        valid_ids = {event.event_id for event in self._events}
        target_id = (
            selected_event_id
            if selected_event_id is not None
            else self._selected_event_id
        )
        self._selected_event_id = target_id if target_id in valid_ids else None
        self.update()

    def select_event(self, event_id: str | None, *, emit_signal: bool = True) -> None:
        valid_ids = {event.event_id for event in self._events}
        new_id = event_id if event_id in valid_ids else None
        self._selected_event_id = new_id
        self.update()
        if emit_signal:
            self.event_selected.emit(self.selected_event())

    # ------------------------------------------------------------------
    # Coordinate mapping
    # ------------------------------------------------------------------

    def _track_bounds(self) -> tuple[float, float]:
        left = _LEFT_MARGIN
        right = max(left + 1.0, float(self.width()) - _RIGHT_MARGIN)
        return left, right

    def time_to_x(self, seconds: float) -> float:
        """Convert a timestamp in seconds to a horizontal widget coordinate."""
        left, right = self._track_bounds()
        span = self.effective_duration
        if span <= 0.0:
            return left
        ratio = max(0.0, min(1.0, float(seconds) / span))
        return left + ratio * (right - left)

    def x_to_time(self, x: float) -> float:
        """Convert a horizontal widget coordinate to a clamped timestamp in seconds."""
        left, right = self._track_bounds()
        span = self.effective_duration
        if span <= 0.0 or right <= left:
            return 0.0
        ratio = max(0.0, min(1.0, (float(x) - left) / (right - left)))
        return round(ratio * span, 3)

    def _candidates_near_x(self, x: float) -> list[TimelineEvent]:
        matches = [
            event
            for event in self.visible_events()
            if abs(self.time_to_x(event.timestamp_seconds) - x) <= _MARKER_HIT_RADIUS_PX
        ]
        matches.sort(
            key=lambda event: (
                abs(self.time_to_x(event.timestamp_seconds) - x),
                event.timestamp_seconds,
                event.event_id,
            )
        )
        return matches

    def event_at_pos(self, x: float, y: float) -> TimelineEvent | None:
        """Return the event marker at *(x, y)*, cycling when markers overlap."""
        if y < _RULER_HEIGHT or not self._events:
            return None
        nearby = self._candidates_near_x(x)
        if not nearby:
            return None
        if self._selected_event_id in [e.event_id for e in nearby] and len(nearby) > 1:
            ids = [e.event_id for e in nearby]
            next_index = (ids.index(self._selected_event_id) + 1) % len(nearby)
            return nearby[next_index]
        return nearby[0]

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position()
        hit_event = self.event_at_pos(pos.x(), pos.y())
        if hit_event is not None:
            self._dragging_event_id = hit_event.event_id
            self._scrubbing_playhead = False
            self.select_event(hit_event.event_id, emit_signal=True)
            self.set_playhead(hit_event.timestamp_seconds)
            self.seek_requested.emit(hit_event.timestamp_seconds)
            event.accept()
            return

        if self.effective_duration > 0.0:
            self._dragging_event_id = None
            self._scrubbing_playhead = True
            target_time = self.x_to_time(pos.x())
            self.set_playhead(target_time)
            self.seek_requested.emit(target_time)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return

        pos = event.position()
        target_time = self.x_to_time(pos.x())
        if self._dragging_event_id is not None:
            self.set_playhead(target_time)
            self.event_moved.emit(self._dragging_event_id, target_time)
            event.accept()
            return

        if self._scrubbing_playhead and self.effective_duration > 0.0:
            self.set_playhead(target_time)
            self.seek_requested.emit(target_time)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging_event_id = None
            self._scrubbing_playhead = False
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if (
            event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
            and self._selected_event_id is not None
        ):
            self.delete_requested.emit(self._selected_event_id)
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def _choose_tick_step(self, duration: float, width_px: float) -> float:
        if duration <= 0.0 or width_px <= 0.0:
            return 1.0
        target_ticks = max(2, int(width_px // 90))
        raw_step = duration / target_ticks
        for step in (0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0):
            if step >= raw_step:
                return step
        return math.ceil(raw_step / 600.0) * 600.0

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(QPen(QColor("#303846"), 1.0))
        painter.setBrush(QColor("#151922"))
        painter.drawRoundedRect(rect, 6.0, 6.0)

        left, right = self._track_bounds()
        track_top = _RULER_HEIGHT + 6.0
        track_bottom = float(self.height()) - 10.0
        track_rect = QRectF(left, track_top, right - left, max(16.0, track_bottom - track_top))

        # Ruler separator and track background
        painter.setPen(QPen(QColor("#28303d"), 1.0))
        painter.drawLine(QPointF(left, _RULER_HEIGHT), QPointF(right, _RULER_HEIGHT))
        painter.setBrush(QColor("#1b202b"))
        painter.drawRoundedRect(track_rect, 4.0, 4.0)

        font = QFont(self.font())
        font.setPointSize(8)
        painter.setFont(font)

        span = self.effective_duration
        if span <= 0.0:
            painter.setPen(QColor("#8a95a5"))
            painter.drawText(
                track_rect,
                Qt.AlignCenter,
                "Import a video and detect activity to see your sound timeline",
            )
            painter.end()
            return

        # Draw ruler ticks
        step = self._choose_tick_step(span, right - left)
        tick_time = 0.0
        while tick_time <= span + 1e-6:
            x = self.time_to_x(tick_time)
            painter.setPen(QPen(QColor("#4a5568"), 1.0))
            painter.drawLine(QPointF(x, _RULER_HEIGHT - 6.0), QPointF(x, _RULER_HEIGHT))
            label = format_timestamp(
                tick_time, include_centiseconds=(step < 1.0)
            )
            painter.setPen(QColor("#9ca6b5"))
            painter.drawText(
                QRectF(x - 28.0, 3.0, 56.0, _RULER_HEIGHT - 8.0),
                Qt.AlignCenter,
                label,
            )
            tick_time += step

        # Draw event markers (keyboard = bar, mouse = diamond, uncertain = dashed)
        for item in self.visible_events():
            mx = self.time_to_x(item.timestamp_seconds)
            is_selected = item.event_id == self._selected_event_id
            base_hex = _CLASSIFICATION_COLOURS.get(
                item.classification, "#3b82f6"
            )
            marker_color = QColor(base_hex if item.enabled else "#5c6573")

            pen_style = (
                Qt.DashLine
                if item.classification is EventClassification.UNCERTAIN
                else Qt.SolidLine
            )
            line_width = 2.6 if is_selected else 1.8
            painter.setPen(
                QPen(
                    QColor("#ffffff") if is_selected else marker_color,
                    line_width,
                    pen_style,
                )
            )
            painter.drawLine(
                QPointF(mx, track_rect.top() + 3.0),
                QPointF(mx, track_rect.bottom() - 3.0),
            )

            if item.classification in (
                EventClassification.MOUSE_LEFT_CLICK,
                EventClassification.MOUSE_RIGHT_CLICK,
            ):
                # Mouse clicks: distinct diamond marker in upper-middle lane
                cy = track_rect.top() + track_rect.height() * 0.34
                r = 5.5 if is_selected else 4.5
                diamond = QPainterPath()
                diamond.moveTo(mx, cy - r)
                diamond.lineTo(mx + r, cy)
                diamond.lineTo(mx, cy + r)
                diamond.lineTo(mx - r, cy)
                diamond.closeSubpath()
                painter.setPen(
                    QPen(QColor("#ffffff") if is_selected else QColor("#151922"), 1.2)
                )
                painter.setBrush(marker_color)
                painter.drawPath(diamond)
            elif item.classification is EventClassification.UNCERTAIN:
                # Uncertain: hollow amber ring
                cy = track_rect.center().y()
                r = 4.5 if is_selected else 3.8
                painter.setPen(
                    QPen(QColor("#ffffff") if is_selected else marker_color, 1.6)
                )
                painter.setBrush(QColor("#1b202b"))
                painter.drawEllipse(QPointF(mx, cy), r, r)
            else:
                # Keyboard tap: rounded key-cap marker in lower-middle lane
                cy = track_rect.top() + track_rect.height() * 0.65
                w = 7.0 if is_selected else 5.5
                h = 10.0 if is_selected else 8.0
                painter.setPen(
                    QPen(QColor("#ffffff") if is_selected else QColor("#151922"), 1.1)
                )
                painter.setBrush(marker_color)
                painter.drawRoundedRect(
                    QRectF(mx - w / 2.0, cy - h / 2.0, w, h),
                    2.0,
                    2.0,
                )

        # Draw playhead
        px = self.time_to_x(self._playhead_seconds)
        playhead_color = QColor("#ff6b6b")
        painter.setPen(QPen(playhead_color, 1.8))
        painter.drawLine(QPointF(px, 4.0), QPointF(px, track_rect.bottom()))

        head = QPainterPath()
        head.moveTo(px - 5.5, 3.0)
        head.lineTo(px + 5.5, 3.0)
        head.lineTo(px, 11.0)
        head.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(playhead_color)
        painter.drawPath(head)
        painter.end()
