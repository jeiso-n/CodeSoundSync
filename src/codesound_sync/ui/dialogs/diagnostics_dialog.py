"""Optional secondary troubleshooting dialog holding technical diagnostics."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from codesound_sync.ui.panels.status_panel import StatusPanel


class DiagnosticsDialog(QDialog):
    """Secondary dialog for troubleshooting logs; hidden from the main creative UI."""

    def __init__(self, status_panel: StatusPanel, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Troubleshooting & Details")
        self.setMinimumSize(680, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        note = QLabel(
            "Technical details and processing history for troubleshooting:"
        )
        note.setObjectName("infoLabel")
        layout.addWidget(note)

        layout.addWidget(status_panel, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
