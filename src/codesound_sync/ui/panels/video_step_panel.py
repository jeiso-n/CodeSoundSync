"""Step 1 (VIDEO): Import a recording, preview it, and detect activity."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from codesound_sync.models.media_info import MediaInfo
from codesound_sync.ui.panels.video_preview_widget import VideoPreviewWidget


class VideoStepPanel(QWidget):
    """First workflow step: video import, preview, and activity detection."""

    import_video_requested = Signal()
    open_project_requested = Signal()
    detect_activity_requested = Signal()
    cancel_detection_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("videoStepPanel")
        self._build_ui()
        self.show_empty_state()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        # Page 0: Friendly empty state
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.addStretch(1)

        card = QFrame()
        card.setObjectName("heroCard")
        card.setMaximumWidth(560)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 36, 36, 36)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignCenter)

        hero_title = QLabel("Choose a video to get started")
        hero_title.setObjectName("heroTitle")
        hero_title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(hero_title)

        hero_sub = QLabel(
            "Import a screen recording of your coding session. "
            "CodeSound Sync will find typing and click moments so you can add natural sound effects."
        )
        hero_sub.setObjectName("mutedText")
        hero_sub.setWordWrap(True)
        hero_sub.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(hero_sub)

        self.empty_import_button = QPushButton("  Import Video")
        self.empty_import_button.setObjectName("primaryActionButton")
        self.empty_import_button.setIcon(
            self.style().standardIcon(QStyle.SP_DialogOpenButton)
        )
        self.empty_import_button.setMinimumHeight(44)
        self.empty_import_button.clicked.connect(self.import_video_requested.emit)
        card_layout.addWidget(self.empty_import_button)

        self.empty_open_project_button = QPushButton("Open Saved Project")
        self.empty_open_project_button.setObjectName("subtleButton")
        self.empty_open_project_button.clicked.connect(
            self.open_project_requested.emit
        )
        card_layout.addWidget(self.empty_open_project_button)

        formats_note = QLabel("Supports MP4, MOV, MKV, AVI, M4V, and WebM")
        formats_note.setObjectName("captionText")
        formats_note.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(formats_note)

        empty_row = QHBoxLayout()
        empty_row.addStretch()
        empty_row.addWidget(card)
        empty_row.addStretch()
        empty_layout.addLayout(empty_row)
        empty_layout.addStretch(1)
        self._stack.addWidget(empty_page)

        # Page 1: Loaded video workspace
        loaded_page = QWidget()
        loaded_layout = QVBoxLayout(loaded_page)
        loaded_layout.setContentsMargins(0, 0, 0, 0)
        loaded_layout.setSpacing(12)

        self.preview_host = QWidget()
        self.preview_host_layout = QVBoxLayout(self.preview_host)
        self.preview_host_layout.setContentsMargins(0, 0, 0, 0)
        loaded_layout.addWidget(self.preview_host, 1)

        # Clean summary & action bar
        action_bar = QFrame()
        action_bar.setObjectName("surfaceCard")
        bar_layout = QHBoxLayout(action_bar)
        bar_layout.setContentsMargins(16, 12, 16, 12)
        bar_layout.setSpacing(12)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.video_name_label = QLabel("No video selected")
        self.video_name_label.setObjectName("sectionTitle")
        self.video_meta_label = QLabel("Duration: —")
        self.video_meta_label.setObjectName("mutedText")
        info_col.addWidget(self.video_name_label)
        info_col.addWidget(self.video_meta_label)
        bar_layout.addLayout(info_col, 1)

        self.change_video_button = QPushButton("Change Video")
        self.change_video_button.clicked.connect(self.import_video_requested.emit)
        bar_layout.addWidget(self.change_video_button)

        self.detection_speed_combo = QComboBox()
        self.detection_speed_combo.addItem("Standard Detection", 0.50)
        self.detection_speed_combo.addItem("Detailed (Sped-Up Video)", 0.25)
        self.detection_speed_combo.addItem("Quick Scan", 1.00)
        self.detection_speed_combo.setToolTip(
            "Choose Detailed for fast-forwarded coding footage."
        )
        bar_layout.addWidget(self.detection_speed_combo)

        self.detect_activity_button = QPushButton("  Detect Activity")
        self.detect_activity_button.setObjectName("primaryActionButton")
        self.detect_activity_button.setIcon(
            self.style().standardIcon(QStyle.SP_MediaSeekForward)
        )
        self.detect_activity_button.setMinimumHeight(40)
        self.detect_activity_button.clicked.connect(self.detect_activity_requested.emit)
        bar_layout.addWidget(self.detect_activity_button)
        loaded_layout.addWidget(action_bar)

        # Inline progress banner (shown only while probing or detecting)
        self.progress_card = QFrame()
        self.progress_card.setObjectName("surfaceCard")
        prog_layout = QHBoxLayout(self.progress_card)
        prog_layout.setContentsMargins(16, 10, 16, 10)
        prog_layout.setSpacing(10)

        self.progress_label = QLabel("Detecting keyboard and mouse activity...")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(10)
        self.cancel_detect_button = QPushButton("Cancel")
        self.cancel_detect_button.clicked.connect(self.cancel_detection_requested.emit)

        prog_layout.addWidget(self.progress_label)
        prog_layout.addWidget(self.progress_bar, 1)
        prog_layout.addWidget(self.cancel_detect_button)
        self.progress_card.hide()
        loaded_layout.addWidget(self.progress_card)

        self._stack.addWidget(loaded_page)

    def attach_preview(self, preview_widget: VideoPreviewWidget) -> None:
        if preview_widget.parent() is not self.preview_host:
            self.preview_host_layout.addWidget(preview_widget)
        preview_widget.show()

    def show_empty_state(self) -> None:
        self._stack.setCurrentIndex(0)
        self.progress_card.hide()

    def show_loaded_video(
        self,
        video_path: Path,
        *,
        missing: bool = False,
        media_info: MediaInfo | None = None,
    ) -> None:
        self._stack.setCurrentIndex(1)
        self.video_name_label.setText(video_path.name)
        if missing:
            self.video_meta_label.setText(
                "Video file not found on disk — saved events can still be reviewed and exported."
            )
            self.detect_activity_button.setEnabled(False)
        elif media_info is not None:
            self.video_meta_label.setText(
                f"Duration: {media_info.duration_str}  •  {media_info.resolution}"
            )
            self.detect_activity_button.setEnabled(True)
        else:
            self.video_meta_label.setText("Preparing video…")
            self.detect_activity_button.setEnabled(False)

    def set_detection_busy(self, busy: bool, message: str = "") -> None:
        self.empty_import_button.setEnabled(not busy)
        self.change_video_button.setEnabled(not busy)
        self.detection_speed_combo.setEnabled(not busy)
        self.detect_activity_button.setEnabled(not busy)
        if busy:
            self.progress_label.setText(
                message or "Detecting keyboard and mouse activity..."
            )
            self.progress_card.show()
        else:
            self.progress_card.hide()
