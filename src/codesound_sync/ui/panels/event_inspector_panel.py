"""Inspector panel for viewing, editing, and auditioning timeline sound events."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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


class EventInspectorPanel(QWidget):
    """Controls for adding, editing, deleting, and previewing a TimelineEvent."""

    add_event_requested = Signal()
    delete_event_requested = Signal(str)  # event_id
    event_modified = Signal(object)  # TimelineEvent
    preview_sound_requested = Signal(object, object)  # TimelineEvent, float | None
    preview_mix_requested = Signal()
    stop_preview_requested = Signal()
    export_timeline_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("eventInspectorPanel")
        self._current_event: TimelineEvent | None = None
        self._max_timestamp: float = 36_000.0
        self._updating_fields = False
        self._variation_step_index = 0

        self._build_ui()
        self.set_event(None)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Row 1: Action buttons + summary badge
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.add_event_button = QPushButton("Add Event")
        self.add_event_button.setToolTip("Add a sound event at the current playhead time.")
        self.add_event_button.clicked.connect(self.add_event_requested.emit)
        top_row.addWidget(self.add_event_button)

        self.delete_event_button = QPushButton("Delete Event")
        self.delete_event_button.setToolTip("Remove the selected event from the timeline.")
        self.delete_event_button.clicked.connect(self._on_delete_clicked)
        top_row.addWidget(self.delete_event_button)

        self.preview_sound_button = QPushButton("Preview Sound")
        self.preview_sound_button.setToolTip("Audition the selected event's sound effect.")
        self.preview_sound_button.clicked.connect(self._on_preview_clicked)
        top_row.addWidget(self.preview_sound_button)

        self.audition_variation_button = QPushButton("Try Variation")
        self.audition_variation_button.setToolTip(
            "Cycle and audition a slight pitch/duration variation for this event."
        )
        self.audition_variation_button.clicked.connect(self._on_try_variation_clicked)
        top_row.addWidget(self.audition_variation_button)

        top_row.addStretch()

        self.preview_mix_button = QPushButton("Preview Mix")
        self.preview_mix_button.setToolTip(
            "Audition the full synchronized timeline sound-effects mix."
        )
        self.preview_mix_button.clicked.connect(self.preview_mix_requested.emit)
        top_row.addWidget(self.preview_mix_button)

        self.stop_preview_button = QPushButton("Stop Audio")
        self.stop_preview_button.setToolTip("Stop any currently playing audio preview.")
        self.stop_preview_button.clicked.connect(self.stop_preview_requested.emit)
        top_row.addWidget(self.stop_preview_button)

        self.export_timeline_button = QPushButton("Export Timeline WAV")
        self.export_timeline_button.setObjectName("primaryButton")
        self.export_timeline_button.setToolTip(
            "Render all included timeline sound events to a WAV file."
        )
        self.export_timeline_button.clicked.connect(
            self.export_timeline_requested.emit
        )
        top_row.addWidget(self.export_timeline_button)
        layout.addLayout(top_row)

        # Row 2: Editable event properties
        props_row = QHBoxLayout()
        props_row.setSpacing(8)

        props_row.addWidget(QLabel("Time:"))
        self.timestamp_spin = QDoubleSpinBox()
        self.timestamp_spin.setRange(0.0, self._max_timestamp)
        self.timestamp_spin.setDecimals(2)
        self.timestamp_spin.setSingleStep(0.05)
        self.timestamp_spin.setSuffix(" s")
        self.timestamp_spin.valueChanged.connect(self._on_field_edited)
        props_row.addWidget(self.timestamp_spin)

        props_row.addWidget(QLabel("Type:"))
        self.classification_combo = QComboBox()
        for classification in EventClassification:
            self.classification_combo.addItem(
                classification.label, classification.value
            )
        self.classification_combo.currentIndexChanged.connect(self._on_field_edited)
        props_row.addWidget(self.classification_combo)

        self.enabled_checkbox = QCheckBox("Include")
        self.enabled_checkbox.setToolTip(
            "Include this event when exporting the timeline sound-effects WAV."
        )
        self.enabled_checkbox.toggled.connect(self._on_field_edited)
        props_row.addWidget(self.enabled_checkbox)

        props_row.addWidget(QLabel("Intensity:"))
        self.intensity_spin = QDoubleSpinBox()
        self.intensity_spin.setRange(0.05, 1.0)
        self.intensity_spin.setDecimals(2)
        self.intensity_spin.setSingleStep(0.05)
        self.intensity_spin.valueChanged.connect(self._on_field_edited)
        props_row.addWidget(self.intensity_spin)

        props_row.addWidget(QLabel("Variation:"))
        self.variation_spin = QDoubleSpinBox()
        self.variation_spin.setRange(-1.0, 1.0)
        self.variation_spin.setDecimals(2)
        self.variation_spin.setSingleStep(0.1)
        self.variation_spin.valueChanged.connect(self._on_field_edited)
        props_row.addWidget(self.variation_spin)

        props_row.addStretch()
        layout.addLayout(props_row)

        # Row 3: Source, confidence, and evidence details
        self.details_label = QLabel("No event selected.")
        self.details_label.setObjectName("infoLabel")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.details_label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_event(self) -> TimelineEvent | None:
        return self._current_event

    def set_max_timestamp(self, duration_seconds: float | None) -> None:
        limit = (
            max(1.0, float(duration_seconds))
            if duration_seconds is not None and duration_seconds > 0
            else 36_000.0
        )
        self._max_timestamp = limit
        self.timestamp_spin.setMaximum(limit)

    def set_event(self, event: TimelineEvent | None) -> None:
        self._current_event = event
        has_event = event is not None
        self._updating_fields = True
        try:
            self.delete_event_button.setEnabled(has_event)
            self.timestamp_spin.setEnabled(has_event)
            self.classification_combo.setEnabled(has_event)
            self.enabled_checkbox.setEnabled(has_event)
            self.intensity_spin.setEnabled(has_event)
            self.variation_spin.setEnabled(has_event)

            if event is None:
                self.timestamp_spin.setValue(0.0)
                self.classification_combo.setCurrentIndex(0)
                self.enabled_checkbox.setChecked(False)
                self.intensity_spin.setValue(0.7)
                self.variation_spin.setValue(0.0)
                self.preview_sound_button.setEnabled(False)
                self.audition_variation_button.setEnabled(False)
                self.details_label.setText(
                    "No event selected. Click a timeline marker to inspect or edit it, "
                    "or click 'Add Event' to create one at the playhead."
                )
                return

            if event.timestamp_seconds > self.timestamp_spin.maximum():
                self.timestamp_spin.setMaximum(event.timestamp_seconds)
            self.timestamp_spin.setValue(event.timestamp_seconds)

            idx = self.classification_combo.findData(event.classification.value)
            if idx >= 0:
                self.classification_combo.setCurrentIndex(idx)
            self.enabled_checkbox.setChecked(event.enabled)
            self.intensity_spin.setValue(event.intensity)
            self.variation_spin.setValue(event.variation)

            can_preview = event.classification is not EventClassification.UNCERTAIN
            self.preview_sound_button.setEnabled(can_preview)
            self.audition_variation_button.setEnabled(can_preview)
            self.details_label.setText(self._format_details(event))
        finally:
            self._updating_fields = False

    def set_classification(self, classification: EventClassification) -> None:
        """Select *classification* in the dropdown and emit event_modified."""
        idx = self.classification_combo.findData(
            EventClassification(classification).value
        )
        if idx >= 0:
            self.classification_combo.setCurrentIndex(idx)

    def _format_details(self, event: TimelineEvent) -> str:
        source_text = (
            "Detected suggestion"
            if event.source is EventSource.DETECTED
            else "Manual event"
        )
        conf_text = (
            f"{event.confidence:.0%} confidence"
            if event.confidence is not None
            else "user-placed"
        )
        evidence_text = f" — {event.evidence}" if event.evidence else ""
        return f"Source: {source_text} ({conf_text}){evidence_text}"

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_field_edited(self) -> None:
        if self._updating_fields or self._current_event is None:
            return
        raw_classification = self.classification_combo.currentData()
        try:
            classification = EventClassification(raw_classification)
        except (ValueError, TypeError):
            classification = EventClassification.KEYBOARD_TAP

        enabled = self.enabled_checkbox.isChecked()
        # If the user reclassifies a previously uncertain event to a concrete sound,
        # automatically enable it when the classification itself just changed.
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
            intensity=round(float(self.intensity_spin.value()), 2),
            variation=round(float(self.variation_spin.value()), 2),
        )
        self._current_event = updated
        can_preview = updated.classification is not EventClassification.UNCERTAIN
        self.preview_sound_button.setEnabled(can_preview)
        self.audition_variation_button.setEnabled(can_preview)
        self.details_label.setText(self._format_details(updated))
        self.event_modified.emit(updated)

    def _on_delete_clicked(self) -> None:
        if self._current_event is not None:
            self.delete_event_requested.emit(self._current_event.event_id)

    def _on_preview_clicked(self) -> None:
        if self._current_event is not None:
            self.preview_sound_requested.emit(self._current_event, None)

    def _on_try_variation_clicked(self) -> None:
        if self._current_event is None:
            return
        candidates = (-0.6, -0.3, 0.0, 0.3, 0.6)
        next_var = candidates[self._variation_step_index % len(candidates)]
        self._variation_step_index += 1
        self.variation_spin.setValue(next_var)
        if self._current_event is not None:
            self.preview_sound_requested.emit(self._current_event, next_var)
