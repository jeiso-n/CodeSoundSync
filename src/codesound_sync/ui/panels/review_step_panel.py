"""Step 2 (REVIEW): Visual timeline, event filtering, and intuitive editing."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from codesound_sync.models.timeline_event import (
    EventClassification,
    EventSource,
    TimelineEvent,
)
from codesound_sync.ui.panels.timeline_widget import TimelineWidget
from codesound_sync.ui.panels.video_preview_widget import VideoPreviewWidget


class ReviewStepPanel(QWidget):
    """Second workflow step: inspect, filter, add, move, and edit sound events."""

    add_event_requested = Signal(object)  # EventClassification
    delete_event_requested = Signal(str)  # event_id
    event_modified = Signal(object)  # TimelineEvent
    preview_sound_requested = Signal(object)  # TimelineEvent
    redetect_requested = Signal()
    continue_to_sound_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewStepPanel")
        self._current_event: TimelineEvent | None = None
        self._updating_fields = False
        self._build_ui()
        self.set_selected_event(None)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Compact preview host
        self.preview_host = QWidget()
        self.preview_host.setMaximumHeight(260)
        self.preview_host_layout = QVBoxLayout(self.preview_host)
        self.preview_host_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview_host)

        # Filter & legend bar
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)

        filter_label = QLabel("Show:")
        filter_label.setObjectName("mutedText")
        filter_bar.addWidget(filter_label)

        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, text in (
            ("all", "All"),
            ("keyboard", "Keyboard"),
            ("mouse", "Mouse Clicks"),
            ("uncertain", "Uncertain"),
        ):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("filterPill")
            btn.clicked.connect(lambda _=False, k=key: self._on_filter_clicked(k))
            self._filter_group.addButton(btn)
            filter_bar.addWidget(btn)
            self.filter_buttons[key] = btn
        self.filter_buttons["all"].setChecked(True)

        filter_bar.addSpacing(12)
        self.counts_label = QLabel("0 keyboard  •  0 mouse  •  0 uncertain")
        self.counts_label.setObjectName("mutedText")
        filter_bar.addWidget(self.counts_label)
        filter_bar.addStretch()

        legend = QLabel(
            "■ Key Tap   ◆ Mouse Click   ◯ Uncertain (muted until confirmed)"
        )
        legend.setObjectName("captionText")
        filter_bar.addWidget(legend)
        layout.addLayout(filter_bar)

        # Interactive timeline
        self.timeline_widget = TimelineWidget()
        layout.addWidget(self.timeline_widget)

        # Uncertain explanation banner (shown when uncertain events exist)
        self.uncertain_banner = QLabel(
            "Dashed amber markers are uncertain visual changes (like scrolling or screen switches). "
            "They stay silent unless you select one and change its type to Keyboard or Mouse."
        )
        self.uncertain_banner.setObjectName("infoBanner")
        self.uncertain_banner.setWordWrap(True)
        self.uncertain_banner.hide()
        layout.addWidget(self.uncertain_banner)

        # Event editing card
        editor_card = QFrame()
        editor_card.setObjectName("surfaceCard")
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(14, 10, 14, 10)
        editor_layout.setSpacing(8)

        # Quick add & actions row
        add_row = QHBoxLayout()
        add_row.setSpacing(8)

        self.add_key_button = QPushButton("+ Key Tap")
        self.add_key_button.setToolTip("Add a keyboard tap at the current playhead.")
        self.add_key_button.clicked.connect(
            lambda: self.add_event_requested.emit(EventClassification.KEYBOARD_TAP)
        )
        add_row.addWidget(self.add_key_button)

        self.add_left_click_button = QPushButton("+ Left Click")
        self.add_left_click_button.setToolTip("Add a mouse left click at the current playhead.")
        self.add_left_click_button.clicked.connect(
            lambda: self.add_event_requested.emit(EventClassification.MOUSE_LEFT_CLICK)
        )
        add_row.addWidget(self.add_left_click_button)

        self.add_right_click_button = QPushButton("+ Right Click")
        self.add_right_click_button.setToolTip("Add a mouse right click at the current playhead.")
        self.add_right_click_button.clicked.connect(
            lambda: self.add_event_requested.emit(EventClassification.MOUSE_RIGHT_CLICK)
        )
        add_row.addWidget(self.add_right_click_button)

        self.delete_event_button = QPushButton("Remove")
        self.delete_event_button.clicked.connect(self._on_delete_clicked)
        add_row.addWidget(self.delete_event_button)

        add_row.addStretch()

        self.redetect_button = QPushButton("Re-detect Activity")
        self.redetect_button.setToolTip(
            "Run detection again while keeping your manual and edited events."
        )
        self.redetect_button.clicked.connect(self.redetect_requested.emit)
        add_row.addWidget(self.redetect_button)

        self.next_sound_button = QPushButton("Adjust Sounds →")
        self.next_sound_button.setObjectName("primaryActionButton")
        self.next_sound_button.clicked.connect(self.continue_to_sound_requested.emit)
        add_row.addWidget(self.next_sound_button)
        editor_layout.addLayout(add_row)

        # Selected event properties row
        props_row = QHBoxLayout()
        props_row.setSpacing(10)

        props_row.addWidget(QLabel("Time:"))
        self.timestamp_spin = QDoubleSpinBox()
        self.timestamp_spin.setRange(0.0, 36_000.0)
        self.timestamp_spin.setDecimals(2)
        self.timestamp_spin.setSingleStep(0.05)
        self.timestamp_spin.setSuffix(" s")
        self.timestamp_spin.valueChanged.connect(self._on_field_edited)
        props_row.addWidget(self.timestamp_spin)

        props_row.addWidget(QLabel("Sound Type:"))
        self.classification_combo = QComboBox()
        for classification in EventClassification:
            self.classification_combo.addItem(
                classification.label, classification.value
            )
        self.classification_combo.currentIndexChanged.connect(self._on_field_edited)
        props_row.addWidget(self.classification_combo)

        self.enabled_checkbox = QCheckBox("Play this sound")
        self.enabled_checkbox.toggled.connect(self._on_field_edited)
        props_row.addWidget(self.enabled_checkbox)

        self.preview_event_button = QPushButton("Hear Sound")
        self.preview_event_button.clicked.connect(self._on_preview_clicked)
        props_row.addWidget(self.preview_event_button)

        props_row.addStretch()
        editor_layout.addLayout(props_row)

        self.details_label = QLabel(
            "Select any marker on the timeline to move, edit, or remove it."
        )
        self.details_label.setObjectName("mutedText")
        self.details_label.setWordWrap(True)
        editor_layout.addWidget(self.details_label)

        layout.addWidget(editor_card)

    def attach_preview(self, preview_widget: VideoPreviewWidget) -> None:
        if preview_widget.parent() is not self.preview_host:
            self.preview_host_layout.addWidget(preview_widget)
        preview_widget.show()

    def update_event_summary(self, events: list[TimelineEvent] | tuple[TimelineEvent, ...]) -> None:
        kb = sum(
            1 for e in events
            if e.enabled and e.classification is EventClassification.KEYBOARD_TAP
        )
        mouse = sum(
            1 for e in events
            if e.enabled
            and e.classification in (
                EventClassification.MOUSE_LEFT_CLICK,
                EventClassification.MOUSE_RIGHT_CLICK,
            )
        )
        uncertain = sum(
            1 for e in events
            if e.classification is EventClassification.UNCERTAIN
        )
        self.counts_label.setText(
            f"{kb} keyboard  •  {mouse} mouse  •  {uncertain} uncertain"
        )
        self.uncertain_banner.setVisible(uncertain > 0)

    def set_max_timestamp(self, duration_seconds: float | None) -> None:
        limit = (
            max(1.0, float(duration_seconds))
            if duration_seconds is not None and duration_seconds > 0
            else 36_000.0
        )
        self.timestamp_spin.setMaximum(limit)

    def set_selected_event(self, event: TimelineEvent | None) -> None:
        self._current_event = event
        has_event = event is not None
        self._updating_fields = True
        try:
            self.delete_event_button.setEnabled(has_event)
            self.timestamp_spin.setEnabled(has_event)
            self.classification_combo.setEnabled(has_event)
            self.enabled_checkbox.setEnabled(has_event)

            if event is None:
                self.timestamp_spin.setValue(0.0)
                self.classification_combo.setCurrentIndex(0)
                self.enabled_checkbox.setChecked(False)
                self.preview_event_button.setEnabled(False)
                self.details_label.setText(
                    "Click a marker on the timeline to adjust it, drag markers to shift timing, "
                    "or add new keyboard/mouse sounds at the playhead."
                )
                return

            if event.timestamp_seconds > self.timestamp_spin.maximum():
                self.timestamp_spin.setMaximum(event.timestamp_seconds)
            self.timestamp_spin.setValue(event.timestamp_seconds)
            idx = self.classification_combo.findData(event.classification.value)
            if idx >= 0:
                self.classification_combo.setCurrentIndex(idx)
            self.enabled_checkbox.setChecked(event.enabled)
            self.preview_event_button.setEnabled(
                event.classification is not EventClassification.UNCERTAIN
            )
            source_desc = (
                "Added by you"
                if event.source is EventSource.MANUAL
                else "Automatically detected"
            )
            if event.classification is EventClassification.UNCERTAIN:
                self.details_label.setText(
                    f"{source_desc} • Uncertain visual change. Change Sound Type to Keyboard Tap "
                    "or Mouse Click if you want a sound here."
                )
            else:
                self.details_label.setText(
                    f"{source_desc} • {event.classification.label} at {event.timestamp_seconds:.2f}s"
                )
        finally:
            self._updating_fields = False

    def set_classification(self, classification: EventClassification) -> None:
        idx = self.classification_combo.findData(
            EventClassification(classification).value
        )
        if idx >= 0:
            self.classification_combo.setCurrentIndex(idx)

    def _on_filter_clicked(self, mode: str) -> None:
        self.timeline_widget.set_filter(mode)

    def _on_field_edited(self) -> None:
        if self._updating_fields or self._current_event is None:
            return
        raw_cls = self.classification_combo.currentData()
        try:
            classification = EventClassification(raw_cls)
        except (ValueError, TypeError):
            classification = EventClassification.KEYBOARD_TAP

        enabled = self.enabled_checkbox.isChecked()
        if (
            self._current_event.classification is EventClassification.UNCERTAIN
            and classification is not EventClassification.UNCERTAIN
            and not self._current_event.enabled
        ):
            enabled = True
            self._updating_fields = True
            self.enabled_checkbox.setChecked(True)
            self._updating_fields = False

        updated = replace(
            self._current_event,
            timestamp_seconds=round(float(self.timestamp_spin.value()), 3),
            classification=classification,
            enabled=enabled,
            user_edited=True,
        )
        self._current_event = updated
        self.preview_event_button.setEnabled(
            updated.classification is not EventClassification.UNCERTAIN
        )
        self.event_modified.emit(updated)

    def _on_delete_clicked(self) -> None:
        if self._current_event is not None:
            self.delete_event_requested.emit(self._current_event.event_id)

    def _on_preview_clicked(self) -> None:
        if self._current_event is not None:
            self.preview_sound_requested.emit(self._current_event)
