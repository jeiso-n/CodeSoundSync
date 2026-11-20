"""Review activity-analysis candidates before turning them into sound effects."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from codesound_sync.models.activity_candidate import (
    ActivityAnalysisResult,
    ActivityCandidate,
)


class ActivityReviewDialog(QDialog):
    """Checkbox table for reviewing and selecting visual-activity candidates."""

    apply_requested = Signal(object)  # tuple[ActivityCandidate, ...]
    generate_requested = Signal(object)  # tuple[ActivityCandidate, ...]

    def __init__(self, result: ActivityAnalysisResult, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review Video Activity")
        self.setMinimumSize(780, 440)
        self._candidates = result.candidates

        layout = QVBoxLayout(self)
        summary = QLabel(
            f"Detected {len(result.candidates)} activity moment(s) in your video."
        )
        layout.addWidget(summary)
        note = QLabel(
            "Choose which detected moments to add to your timeline. "
            "Your manually added and edited events will be kept."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(len(result.candidates), 5)
        self.table.setHorizontalHeaderLabels(
            ["Include", "Time", "Type", "Confidence", "Details"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 165)
        self.table.setColumnWidth(3, 90)
        for row, candidate in enumerate(result.candidates):
            include = QTableWidgetItem()
            include.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            include.setCheckState(
                Qt.Checked if candidate.to_sound_event() is not None else Qt.Unchecked
            )
            self.table.setItem(row, 0, include)

            ts_text = f"{candidate.timestamp_seconds:.2f} s"
            if len(candidate.event_timestamps) > 1:
                ts_text = (
                    f"{candidate.timestamp_seconds:.2f} s "
                    f"({len(candidate.event_timestamps)} taps)"
                )
            self.table.setItem(row, 1, QTableWidgetItem(ts_text))
            self.table.setItem(
                row, 2, QTableWidgetItem(candidate.candidate_type.value)
            )
            self.table.setItem(
                row, 3, QTableWidgetItem(f"{candidate.confidence:.0%}")
            )
            self.table.setItem(row, 4, QTableWidgetItem(candidate.evidence))
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Apply Selected to Timeline")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self._apply_selected)
        buttons.addWidget(self.apply_button)

        self.generate_button = QPushButton("Generate Sound Effects Track")
        self.generate_button.clicked.connect(self._generate_selected)
        buttons.addWidget(self.generate_button)
        buttons.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def selected_candidates(self) -> tuple[ActivityCandidate, ...]:
        """Return only rows currently checked by the reviewer."""
        return tuple(
            candidate
            for row, candidate in enumerate(self._candidates)
            if self.table.item(row, 0).checkState() == Qt.Checked
        )

    def _apply_selected(self) -> None:
        self.apply_requested.emit(self.selected_candidates())
        self.close()

    def _generate_selected(self) -> None:
        self.generate_requested.emit(self.selected_candidates())
