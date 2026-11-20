"""Step 4 (EXPORT): Destination selection, WAV format summary, and export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from codesound_sync.config import PROJECT_ROOT
from codesound_sync.models.timeline_event import EventClassification, TimelineEvent
from codesound_sync.services.video_preview_service import format_timestamp


class ExportStepPanel(QWidget):
    """Fourth workflow step: export synchronized WAV audio for video editors."""

    browse_output_requested = Signal()
    export_audio_requested = Signal()
    open_output_folder_requested = Signal()
    preview_mix_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("exportStepPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Readiness summary card
        summary_card = QFrame()
        summary_card.setObjectName("surfaceCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(20, 16, 20, 16)
        summary_layout.setSpacing(6)

        self.summary_title = QLabel("Your audio is ready to export")
        self.summary_title.setObjectName("sectionTitle")
        self.summary_details = QLabel(
            "Import a video and detect or add events on the timeline first."
        )
        self.summary_details.setObjectName("mutedText")
        self.summary_details.setWordWrap(True)
        summary_layout.addWidget(self.summary_title)
        summary_layout.addWidget(self.summary_details)
        layout.addWidget(summary_card)

        # Destination & Project settings card
        dest_card = QFrame()
        dest_card.setObjectName("surfaceCard")
        dest_layout = QVBoxLayout(dest_card)
        dest_layout.setContentsMargins(20, 16, 20, 16)
        dest_layout.setSpacing(10)

        dest_header = QLabel("Export Settings")
        dest_header.setObjectName("sectionTitle")
        dest_layout.addWidget(dest_header)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Project Name:"))
        self.project_name_edit = QLineEdit()
        self.project_name_edit.setPlaceholderText("My Coding Tutorial")
        name_row.addWidget(self.project_name_edit, 1)
        dest_layout.addLayout(name_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output Folder:"))
        self.output_location_edit = QLineEdit(str(PROJECT_ROOT / "output"))
        self.output_location_edit.setReadOnly(True)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self.browse_output_requested.emit)
        out_row.addWidget(self.output_location_edit, 1)
        out_row.addWidget(self.browse_button)
        dest_layout.addLayout(out_row)

        format_note = QLabel(
            "Format: WAV (44.1 kHz, 16-bit PCM)  •  Compatible with Premiere Pro, "
            "DaVinci Resolve, CapCut, and all major video editors."
        )
        format_note.setObjectName("mutedText")
        format_note.setWordWrap(True)
        dest_layout.addWidget(format_note)
        layout.addWidget(dest_card)

        # Export CTA row
        cta_row = QHBoxLayout()
        cta_row.setSpacing(10)

        self.preview_before_export_button = QPushButton("Preview Mix")
        self.preview_before_export_button.setMinimumHeight(42)
        self.preview_before_export_button.clicked.connect(self.preview_mix_requested.emit)
        cta_row.addWidget(self.preview_before_export_button)

        cta_row.addStretch()

        self.export_audio_button = QPushButton("  Export Audio (WAV)")
        self.export_audio_button.setObjectName("primaryActionButton")
        self.export_audio_button.setIcon(
            self.style().standardIcon(QStyle.SP_DialogSaveButton)
        )
        self.export_audio_button.setMinimumHeight(44)
        self.export_audio_button.setMinimumWidth(210)
        self.export_audio_button.clicked.connect(self.export_audio_requested.emit)
        cta_row.addWidget(self.export_audio_button)
        layout.addLayout(cta_row)

        # Progress bar (shown briefly during export)
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 0)
        self.export_progress.setFixedHeight(10)
        self.export_progress.hide()
        layout.addWidget(self.export_progress)

        # Success confirmation card
        self.success_card = QFrame()
        self.success_card.setObjectName("successCard")
        succ_layout = QHBoxLayout(self.success_card)
        succ_layout.setContentsMargins(18, 14, 18, 14)
        succ_layout.setSpacing(12)

        succ_text_col = QVBoxLayout()
        self.success_title = QLabel("Audio exported successfully.")
        self.success_title.setObjectName("sectionTitle")
        self.success_path_label = QLabel("")
        self.success_path_label.setObjectName("mutedText")
        self.success_path_label.setWordWrap(True)
        self.success_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        succ_text_col.addWidget(self.success_title)
        succ_text_col.addWidget(self.success_path_label)
        succ_layout.addLayout(succ_text_col, 1)

        self.open_folder_button = QPushButton("Open Output Folder")
        self.open_folder_button.clicked.connect(self.open_output_folder_requested.emit)
        succ_layout.addWidget(self.open_folder_button)
        self.success_card.hide()
        layout.addWidget(self.success_card)

        layout.addStretch(1)

    def update_summary(
        self,
        events: list[TimelineEvent] | tuple[TimelineEvent, ...],
        duration_seconds: float | None,
    ) -> None:
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
        total = kb + mouse
        dur_text = format_timestamp(duration_seconds) if duration_seconds else "00:00.00"
        if total == 0:
            self.summary_title.setText("No sounds scheduled yet")
            self.summary_details.setText(
                "Detect activity from a video or add keyboard/mouse events on the Review timeline."
            )
            self.export_audio_button.setEnabled(False)
            self.preview_before_export_button.setEnabled(False)
        else:
            self.summary_title.setText("Your audio is ready to export")
            self.summary_details.setText(
                f"{kb} keyboard tap(s) and {mouse} mouse click(s)  •  Track duration: {dur_text}"
            )
            self.export_audio_button.setEnabled(True)
            self.preview_before_export_button.setEnabled(True)

    def show_export_success(self, exported_path: Path) -> None:
        self.success_title.setText("Audio exported successfully.")
        self.success_path_label.setText(str(exported_path))
        self.success_card.show()

    def clear_export_success(self) -> None:
        self.success_card.hide()
        self.success_path_label.setText("")
