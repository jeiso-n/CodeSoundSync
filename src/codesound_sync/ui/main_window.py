"""Main CodeSound Sync desktop window — 4-step creative workflow."""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from codesound_sync.config import (
    ACTIVITY_SAMPLE_INTERVAL_SECONDS,
    PROJECT_ROOT,
    PROJECTS_DIR,
    WINDOW_DEFAULT_TITLE,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from codesound_sync.models.activity_candidate import (
    ActivityAnalysisResult,
    ActivityCandidate,
    candidates_to_sound_events,
)
from codesound_sync.models.media_info import MediaInfo
from codesound_sync.models.project import Project
from codesound_sync.models.sound_event import SoundEvent, SoundEventType
from codesound_sync.models.timeline_event import (
    EventClassification,
    EventSource,
    TimelineEvent,
    candidates_to_timeline_events,
    merge_detected_timeline_events,
    timeline_events_to_sound_events,
)
from codesound_sync.services.activity_analysis_service import FrameActivityAnalyzer
from codesound_sync.services.project_service import ProjectFileError, ProjectService
from codesound_sync.services.sound_effects_service import SoundEffectsService
from codesound_sync.services.sound_generator import SoundProfile
from codesound_sync.services.sound_preview_service import (
    SoundPreviewError,
    SoundPreviewService,
)
from codesound_sync.ui.dialogs.activity_review_dialog import ActivityReviewDialog
from codesound_sync.ui.dialogs.diagnostics_dialog import DiagnosticsDialog
from codesound_sync.ui.panels.export_step_panel import ExportStepPanel
from codesound_sync.ui.panels.review_step_panel import ReviewStepPanel
from codesound_sync.ui.panels.sound_step_panel import SoundStepPanel
from codesound_sync.ui.panels.status_panel import StatusPanel
from codesound_sync.ui.panels.video_preview_widget import VideoPreviewWidget
from codesound_sync.ui.panels.video_step_panel import VideoStepPanel
from codesound_sync.ui.workers.activity_analysis_worker import ActivityAnalysisWorker
from codesound_sync.ui.workers.ffprobe_worker import FFprobeWorker

log = logging.getLogger(__name__)

VIDEO_FILTER = (
    "Video files (*.mp4 *.mov *.mkv *.avi *.m4v *.webm);;"
    "All files (*)"
)
PROJECT_FILTER = "CodeSound Sync project files (*.json)"


class MainWindow(QMainWindow):
    """Creative desktop workstation organized into Video, Review, Sound, and Export."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_DEFAULT_TITLE)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self._project_service = ProjectService()
        self._sound_effects_service = SoundEffectsService()
        self._sound_preview_service = SoundPreviewService(self._sound_effects_service)
        self._project: Project | None = None
        self._project_file: Path | None = None
        self._probe_worker: FFprobeWorker | None = None
        self._probe_busy = False
        self._activity_worker: ActivityAnalysisWorker | None = None
        self._review_dialog: ActivityReviewDialog | None = None
        self._activity_result: ActivityAnalysisResult | None = None

        self._build_ui()
        self._apply_theme()
        self._set_busy(False)
        self._switch_step(0)
        self._set_friendly_status("Choose a video to get started.")

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(12)

        # Top header: brand + step navigation + project/help actions
        header = QHBoxLayout()
        header.setSpacing(12)

        brand = QVBoxLayout()
        brand.setSpacing(1)
        title = QLabel("CodeSound Sync")
        title.setObjectName("appTitle")
        subtitle = QLabel("Add natural keyboard & mouse sounds to your videos")
        subtitle.setObjectName("appSubtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addSpacing(20)

        # 4-step workflow navigation
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        step_defs = (
            ("1. Video", QStyle.SP_MediaPlay),
            ("2. Review", QStyle.SP_FileDialogDetailedView),
            ("3. Sound", QStyle.SP_MediaVolume),
            ("4. Export", QStyle.SP_DialogSaveButton),
        )
        for index, (label, icon_enum) in enumerate(step_defs):
            btn = QPushButton(f"  {label}")
            btn.setObjectName("stepNavButton")
            btn.setIcon(self.style().standardIcon(icon_enum))
            btn.setCheckable(True)
            btn.setMinimumHeight(38)
            btn.clicked.connect(lambda _=False, idx=index: self._switch_step(idx))
            self._nav_group.addButton(btn, index)
            self.nav_buttons.append(btn)
            header.addWidget(btn)

        header.addStretch()

        self.open_project_button = QPushButton("Open Project")
        self.open_project_button.clicked.connect(self._choose_project)
        header.addWidget(self.open_project_button)

        self.save_project_button = QPushButton("Save Project")
        self.save_project_button.setEnabled(False)
        self.save_project_button.clicked.connect(self._save_project)
        header.addWidget(self.save_project_button)

        self.diagnostics_button = QPushButton("Details")
        self.diagnostics_button.setObjectName("subtleButton")
        self.diagnostics_button.setToolTip("Open troubleshooting details.")
        self.diagnostics_button.clicked.connect(self._show_diagnostics)
        header.addWidget(self.diagnostics_button)

        outer.addLayout(header)

        # Shared video preview widget (attached dynamically to Video or Review step)
        self.video_preview = VideoPreviewWidget(parent=self)
        self.video_preview.playback_error.connect(self._on_playback_error)
        self.video_preview.position_changed.connect(self._on_preview_position_changed)

        # Main 4-step stacked workspace
        self.step_stack = QStackedWidget()
        self.video_step = VideoStepPanel()
        self.review_step = ReviewStepPanel()
        self.sound_step = SoundStepPanel()
        self.export_step = ExportStepPanel()

        self.step_stack.addWidget(self.video_step)
        self.step_stack.addWidget(self.review_step)
        self.step_stack.addWidget(self.sound_step)
        self.step_stack.addWidget(self.export_step)
        outer.addWidget(self.step_stack, 1)

        # Friendly bottom status bar
        status_bar = QFrame()
        status_bar.setObjectName("friendlyStatusBar")
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(14, 8, 14, 8)
        sb_layout.setSpacing(10)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDotInfo")
        sb_layout.addWidget(self.status_dot)

        self.friendly_status_label = QLabel("Choose a video to get started.")
        self.friendly_status_label.setObjectName("friendlyStatusText")
        sb_layout.addWidget(self.friendly_status_label, 1)

        self.status_details_button = QPushButton("View Details")
        self.status_details_button.setObjectName("subtleButton")
        self.status_details_button.clicked.connect(self._show_diagnostics)
        self.status_details_button.hide()
        sb_layout.addWidget(self.status_details_button)

        outer.addWidget(status_bar)

        # Hidden secondary diagnostics panel (for troubleshooting dialog)
        self.status_panel = StatusPanel()
        self._diagnostics_dialog = DiagnosticsDialog(self.status_panel, self)

        self._connect_step_signals()
        self.setCentralWidget(root)
        self.statusBar().hide()
        self.status_panel.info("Ready. Choose a video to get started.")

    def _connect_step_signals(self) -> None:
        # Step 1: Video
        self.video_step.import_video_requested.connect(self._choose_video)
        self.video_step.open_project_requested.connect(self._choose_project)
        self.video_step.detect_activity_requested.connect(self._analyze_video_activity)
        self.video_step.cancel_detection_requested.connect(self._cancel_activity_analysis)

        # Step 2: Review
        self.review_step.timeline_widget.seek_requested.connect(
            lambda ts: self.video_preview.seek_to(ts, user_initiated=True)
        )
        self.review_step.timeline_widget.event_selected.connect(
            self.review_step.set_selected_event
        )
        self.review_step.timeline_widget.event_moved.connect(
            self._on_timeline_event_moved
        )
        self.review_step.timeline_widget.delete_requested.connect(
            self._delete_timeline_event
        )
        self.review_step.add_event_requested.connect(self._add_timeline_event_at_playhead)
        self.review_step.delete_event_requested.connect(self._delete_timeline_event)
        self.review_step.event_modified.connect(self._on_inspector_event_modified)
        self.review_step.preview_sound_requested.connect(
            lambda evt: self._on_preview_sound_requested(evt, None)
        )
        self.review_step.redetect_requested.connect(self._analyze_video_activity)
        self.review_step.continue_to_sound_requested.connect(
            lambda: self._switch_step(2)
        )

        # Step 3: Sound
        self.sound_step.profile_changed.connect(self._on_sound_profile_changed)
        self.sound_step.preview_sample_requested.connect(self._on_preview_sample_requested)
        self.sound_step.preview_mix_requested.connect(self._preview_timeline_mix)
        self.sound_step.stop_audio_requested.connect(self._stop_sound_preview)
        self.sound_step.continue_to_export_requested.connect(
            lambda: self._switch_step(3)
        )

        # Step 4: Export
        self.export_step.browse_output_requested.connect(self._choose_output_location)
        self.export_step.export_audio_requested.connect(self._export_timeline_sounds)
        self.export_step.open_output_folder_requested.connect(self._open_output_folder)
        self.export_step.preview_mix_requested.connect(self._preview_timeline_mix)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget#appRoot { background: #131720; color: #e8ecf4; font-size: 13px; }
            QLabel#appTitle { color: #f8fafc; font-size: 20px; font-weight: 700; }
            QLabel#appSubtitle { color: #94a3b8; font-size: 12px; }
            QLabel#heroTitle { color: #f8fafc; font-size: 22px; font-weight: 700; }
            QLabel#sectionTitle { color: #f1f5f9; font-size: 15px; font-weight: 600; }
            QLabel#mutedText { color: #94a3b8; font-size: 12px; }
            QLabel#captionText { color: #64748b; font-size: 11px; }
            QLabel#infoLabel { color: #94a3b8; }
            QLabel#infoValue { color: #e2e8f0; }
            QLabel#infoBanner {
                background: #1e2430; border: 1px solid #334155; border-radius: 6px;
                color: #cbd5e1; padding: 8px 12px; font-size: 12px;
            }
            QFrame#heroCard, QFrame#surfaceCard {
                background: #1b212d; border: 1px solid #2b3547; border-radius: 10px;
            }
            QFrame#successCard {
                background: #14261f; border: 1px solid #22543d; border-radius: 10px;
            }
            QFrame#friendlyStatusBar {
                background: #191f2b; border: 1px solid #283244; border-radius: 8px;
            }
            QLabel#previewPlaceholder {
                background: #0e1219; border: 1px solid #2b3547; border-radius: 10px;
                color: #94a3b8; font-size: 14px;
            }
            QLabel#statusDotInfo { color: #38bdf8; font-size: 12px; }
            QLabel#statusDotSuccess { color: #4ade80; font-size: 12px; }
            QLabel#statusDotWarning { color: #fbbf24; font-size: 12px; }
            QLabel#statusDotError { color: #f87171; font-size: 12px; }
            QLineEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox {
                background: #111620; border: 1px solid #334155; border-radius: 6px;
                color: #f1f5f9; padding: 6px 10px;
            }
            QPushButton {
                background: #252e3f; border: 1px solid #374357; border-radius: 6px;
                color: #f1f5f9; padding: 7px 14px; font-weight: 500;
            }
            QPushButton:hover:!disabled { background: #313d52; }
            QPushButton:disabled { color: #64748b; background: #1c222e; border-color: #252d3b; }
            QPushButton#primaryActionButton, QPushButton#primaryButton {
                background: #2563eb; border-color: #3b82f6; color: #ffffff; font-weight: 600;
            }
            QPushButton#primaryActionButton:hover:!disabled, QPushButton#primaryButton:hover:!disabled {
                background: #3b82f6;
            }
            QPushButton#stepNavButton {
                background: transparent; border: 1px solid transparent; border-radius: 8px;
                color: #94a3b8; padding: 6px 14px; font-weight: 600;
            }
            QPushButton#stepNavButton:hover:!checked { background: #1e2534; color: #e2e8f0; }
            QPushButton#stepNavButton:checked {
                background: #2563eb; border-color: #3b82f6; color: #ffffff;
            }
            QPushButton#filterPill {
                background: #1b212d; border: 1px solid #2b3547; border-radius: 14px;
                color: #94a3b8; padding: 4px 12px; font-size: 12px;
            }
            QPushButton#filterPill:checked {
                background: #2563eb; border-color: #3b82f6; color: #ffffff;
            }
            QPushButton#subtleButton {
                background: transparent; border: 1px solid #2b3547; color: #94a3b8;
                padding: 5px 10px;
            }
            QPushButton#subtleButton:hover { background: #1e2534; color: #e2e8f0; }
            QProgressBar {
                background: #111620; border: 1px solid #2b3547; border-radius: 5px;
            }
            QProgressBar::chunk { background: #3b82f6; border-radius: 4px; }
            """
        )

    # ------------------------------------------------------------------
    # Navigation & Status
    # ------------------------------------------------------------------

    def _switch_step(self, index: int) -> None:
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        if index == 0:
            self.video_step.attach_preview(self.video_preview)
        elif index == 1:
            self.review_step.attach_preview(self.video_preview)
        elif index == 3:
            self._refresh_export_summary()
        self.step_stack.setCurrentIndex(index)

    def _set_friendly_status(
        self,
        message: str,
        *,
        level: str = "info",
        show_details: bool = False,
    ) -> None:
        self.friendly_status_label.setText(message)
        dot_name = {
            "info": "statusDotInfo",
            "success": "statusDotSuccess",
            "warning": "statusDotWarning",
            "error": "statusDotError",
        }.get(level, "statusDotInfo")
        self.status_dot.setObjectName(dot_name)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)
        self.status_details_button.setVisible(show_details)

    def _show_diagnostics(self) -> None:
        self._diagnostics_dialog.show()
        self._diagnostics_dialog.raise_()
        self._diagnostics_dialog.activateWindow()

    def _on_preview_position_changed(self, seconds: float) -> None:
        self.review_step.timeline_widget.set_playhead(seconds)

    # ------------------------------------------------------------------
    # Import & Project Open/Save
    # ------------------------------------------------------------------

    def _choose_video(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Import Video", "", VIDEO_FILTER
        )
        if selected:
            self.load_video(Path(selected))

    def _choose_project(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Open Project", str(PROJECTS_DIR), PROJECT_FILTER
        )
        if selected:
            self.load_project(Path(selected))

    def load_project(self, path: Path) -> bool:
        """Load a saved project and restore its state in the window."""
        if self._activity_worker is not None and self._activity_worker.isRunning():
            self._set_friendly_status(
                "Please wait for activity detection to finish first.", level="warning"
            )
            return False
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._set_friendly_status(
                "Please wait while your video is being prepared.", level="warning"
            )
            return False

        path = Path(path)
        try:
            project = self._project_service.load_file(path)
        except ProjectFileError as exc:
            message = f"Could not open project: {exc}"
            log.warning(message)
            self.status_panel.error(message)
            self._set_friendly_status(
                "This project file could not be opened. Please check that it is a valid CodeSound Sync project.",
                level="error",
                show_details=True,
            )
            return False

        self._project = project
        self._project_file = path
        self.export_step.project_name_edit.setText(project.name)
        self.export_step.output_location_edit.setText(
            str(project.output_dir or PROJECT_ROOT / "output")
        )
        self.export_step.clear_export_success()
        self.save_project_button.setEnabled(True)

        try:
            source_exists = (
                project.source_video is not None and project.source_video.is_file()
            )
        except (OSError, ValueError):
            source_exists = False

        if project.source_video is None:
            self.video_preview.clear()
            self.video_step.show_empty_state()
        elif source_exists:
            self.video_preview.set_video(project.source_video)
            self.video_step.show_loaded_video(
                project.source_video, media_info=project.media_info
            )
        else:
            self.video_preview.set_missing_video(project.source_video)
            self.video_step.show_loaded_video(
                project.source_video, missing=True, media_info=project.media_info
            )

        duration = (
            project.media_info.duration_seconds
            if project.media_info is not None
            else None
        )
        self.video_preview.set_duration(duration, load_initial_frame=source_exists)
        self.review_step.timeline_widget.set_duration(duration)
        self._sync_timeline_ui()

        if project.source_video is not None and not source_exists:
            self.status_panel.warning(
                f"Project opened, but the source video cannot be found: {project.source_video}"
            )
            self._set_friendly_status(
                "Project opened, but the original video file could not be found. Saved events are still available.",
                level="warning",
                show_details=True,
            )
        else:
            self.status_panel.success(f"Project opened: {project.name}")
            if project.timeline_events:
                self._set_friendly_status(
                    f"Project '{project.name}' opened. Your audio is ready to review or export.",
                    level="success",
                )
            else:
                self._set_friendly_status(
                    f"Project '{project.name}' opened. Your video is ready.",
                    level="success",
                )
        return True

    def load_video(self, path: Path) -> None:
        """Load and inspect a local video file."""
        path = Path(path)
        if self._activity_worker is not None and self._activity_worker.isRunning():
            self._set_friendly_status(
                "Please wait for activity detection to finish first.", level="warning"
            )
            return
        if not path.is_file():
            self.status_panel.error(f"Video file not found: {path}")
            self._set_friendly_status(
                "That video file could not be found. Please choose another file.",
                level="error",
                show_details=True,
            )
            return
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._set_friendly_status(
                "Please wait while your current video finishes loading.", level="warning"
            )
            return

        self._project = Project(
            name=path.stem or "Untitled Project",
            source_video=path,
            output_dir=Path(self.export_step.output_location_edit.text()),
        )
        self._project_file = None
        self.export_step.project_name_edit.setText(self._project.name)
        self.export_step.clear_export_success()
        self.video_preview.set_video(path)
        self.video_preview.set_duration(None, load_initial_frame=False)
        self.video_step.show_loaded_video(path)
        self.review_step.timeline_widget.set_duration(0.0)
        self._sync_timeline_ui()
        self.save_project_button.setEnabled(True)
        self._set_busy(True)
        self._switch_step(0)
        self._set_friendly_status(f"Preparing {path.name}...")

        worker = FFprobeWorker(path, self)
        self._probe_worker = worker
        worker.progress.connect(self._on_probe_progress)
        worker.media_ready.connect(self._on_probe_ready)
        worker.error.connect(self._on_probe_error)
        worker.finished.connect(self._on_probe_worker_finished)
        worker.start()

    def _set_busy(self, busy: bool) -> None:
        self._probe_busy = busy
        self.open_project_button.setEnabled(not busy)
        self.video_step.set_detection_busy(
            busy,
            "Preparing your video..." if busy else "",
        )
        if not busy:
            can_detect = (
                self._project is not None
                and self._project.source_video is not None
                and self._project.source_video.is_file()
                and self._project.media_info is not None
                and self._activity_worker is None
            )
            self.video_step.detect_activity_button.setEnabled(can_detect)

    def _on_probe_progress(self, message: str) -> None:
        self.status_panel.info(message)

    def _on_probe_ready(self, info: MediaInfo) -> None:
        if self._project is None:
            return
        self._project.media_info = info
        self._project.touch()
        self.video_step.show_loaded_video(info.path, media_info=info)
        self.video_preview.set_duration(info.duration_seconds, load_initial_frame=True)
        self.review_step.timeline_widget.set_duration(info.duration_seconds)
        self._sync_timeline_ui()
        self.save_project_button.setEnabled(True)

        self.status_panel.success(
            f"Media inspected: {info.path.name} — {info.duration_str}, "
            f"{info.resolution}, {info.frame_rate_str}."
        )
        if not info.audio_streams:
            self.status_panel.warning("No audio streams were found in this video.")
        self._set_friendly_status(
            "Your video is ready. Click Detect Activity to find typing and click moments.",
            level="success",
        )

    def _on_probe_error(self, message: str) -> None:
        self.status_panel.error(message)
        self._set_friendly_status(
            "Could not inspect this video. Check that the file is not damaged and FFmpeg is installed.",
            level="error",
            show_details=True,
        )

    def _on_playback_error(self, message: str) -> None:
        self.status_panel.warning(f"Video preview failed: {message}")
        self._set_friendly_status(
            "Video preview could not play this file, but you can still edit and export sounds.",
            level="warning",
            show_details=True,
        )

    def _on_probe_worker_finished(self) -> None:
        worker = self._probe_worker
        if worker is not None:
            if self._probe_worker is worker:
                self._probe_worker = None
            self._set_busy(False)
            worker.deleteLater()

    def _choose_output_location(self) -> None:
        current = self.export_step.output_location_edit.text()
        selected = QFileDialog.getExistingDirectory(
            self, "Choose Output Folder", current
        )
        if not selected:
            return
        output_path = Path(selected)
        self.export_step.output_location_edit.setText(str(output_path))
        if self._project is not None:
            self._project.output_dir = output_path
            self._project.touch()

    def _save_project(self) -> None:
        if self._project is None:
            return
        project_name = self.export_step.project_name_edit.text().strip()
        if not project_name:
            self._set_friendly_status(
                "Enter a project name in the Export tab before saving.", level="warning"
            )
            return
        self._project.name = project_name
        self._project.output_dir = Path(self.export_step.output_location_edit.text())
        try:
            saved_path = self._project_service.save(
                self._project, path=self._project_file
            )
        except OSError as exc:
            log.exception("Could not save project")
            self.status_panel.error(f"Could not save project: {exc}")
            self._set_friendly_status(
                "Could not save the project file. Check folder permissions and try again.",
                level="error",
                show_details=True,
            )
            return
        self._project_file = saved_path
        self.status_panel.success(f"Project saved locally: {saved_path.name}")
        self._set_friendly_status(
            f"Project saved: {saved_path.name}", level="success"
        )

    # ------------------------------------------------------------------
    # Activity Detection & Non-Destructive Review
    # ------------------------------------------------------------------

    def _analyze_video_activity(self) -> None:
        if self._project is None or self._project.source_video is None:
            self._set_friendly_status("Choose a video to get started.", level="warning")
            return
        if self._activity_worker is not None:
            return
        if not self._project.source_video.is_file():
            self.status_panel.error(
                f"Video file not found: {self._project.source_video}"
            )
            self._set_friendly_status(
                "The selected video file could not be found.", level="error", show_details=True
            )
            return
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._set_friendly_status(
                "Please wait while your video finishes loading.", level="warning"
            )
            return

        if self._review_dialog is not None:
            self._review_dialog.close()
            self._review_dialog.deleteLater()
            self._review_dialog = None

        sample_interval = self.video_step.detection_speed_combo.currentData()
        if not isinstance(sample_interval, (int, float)):
            sample_interval = ACTIVITY_SAMPLE_INTERVAL_SECONDS

        analyzer = FrameActivityAnalyzer(sample_interval_seconds=float(sample_interval))
        worker = ActivityAnalysisWorker(self._project.source_video, analyzer, self)
        self._activity_worker = worker
        worker.progress.connect(self._on_activity_progress)
        worker.result_ready.connect(self._on_activity_ready)
        worker.error.connect(self._on_activity_error)
        worker.cancelled.connect(self._on_activity_cancelled)
        worker.finished.connect(self._on_activity_worker_finished)

        self.open_project_button.setEnabled(False)
        self.video_step.set_detection_busy(
            True, "Detecting keyboard and mouse activity..."
        )
        self._set_friendly_status("Detecting keyboard and mouse activity...")
        worker.start()

    def _cancel_activity_analysis(self) -> None:
        if self._activity_worker is not None:
            self._activity_worker.cancel()

    def _on_activity_progress(self, message: str) -> None:
        self.status_panel.info(message)

    def _on_activity_ready(self, result: ActivityAnalysisResult) -> None:
        self.status_panel.success(
            f"Activity analysis complete: {len(result.candidates)} candidate(s) "
            f"from {result.sampled_frame_count} sampled frames."
        )
        self._activity_result = result
        if self._project is not None:
            detected_events = candidates_to_timeline_events(result.candidates)
            self._project.timeline_events = merge_detected_timeline_events(
                self._project.timeline_events,
                detected_events,
            )
            self._project.touch()
            if (
                self.video_preview.duration_seconds <= 0.0
                and result.video_duration_seconds > 0.0
            ):
                self.video_preview.set_duration(
                    result.video_duration_seconds, load_initial_frame=False
                )
                self.review_step.timeline_widget.set_duration(
                    result.video_duration_seconds
                )
            self._sync_timeline_ui()

        self._switch_step(1)
        self._set_friendly_status(
            "Activity detection complete. Review the detected sounds.",
            level="success",
        )

    def _on_activity_error(self, message: str) -> None:
        self.status_panel.error(f"Video activity analysis failed: {message}")
        self._set_friendly_status(
            "Could not detect activity in this video. Check that the file plays normally and try again.",
            level="error",
            show_details=True,
        )

    def _on_activity_cancelled(self) -> None:
        self.status_panel.warning("Video activity analysis cancelled.")
        self._set_friendly_status("Activity detection cancelled.", level="warning")

    def _on_activity_worker_finished(self) -> None:
        worker = self._activity_worker
        if worker is not None:
            if self._activity_worker is worker:
                self._activity_worker = None
            worker.deleteLater()
            self._set_busy(False)

    def _apply_activity_candidates(
        self, candidates: tuple[ActivityCandidate, ...]
    ) -> None:
        if self._project is None or self._activity_result is None:
            return
        detected_events = candidates_to_timeline_events(
            self._activity_result.candidates,
            selected_candidates=candidates,
        )
        self._project.timeline_events = merge_detected_timeline_events(
            self._project.timeline_events,
            detected_events,
        )
        self._project.touch()
        self._sync_timeline_ui()
        self._set_friendly_status(
            "Review updated. Your manual and edited sounds were preserved.",
            level="success",
        )

    def _generate_activity_sounds(
        self, candidates: tuple[ActivityCandidate, ...]
    ) -> None:
        self._apply_activity_candidates(candidates)
        events = candidates_to_sound_events(candidates)
        if not events:
            self._set_friendly_status(
                "No confirmed sounds selected. Change uncertain markers to Keyboard or Mouse first.",
                level="warning",
            )
            return
        duration_seconds = (
            self._activity_result.video_duration_seconds
            if self._activity_result is not None
            else None
        )
        self._render_sound_events_track(events, duration_seconds=duration_seconds)

    # ------------------------------------------------------------------
    # Timeline Editing
    # ------------------------------------------------------------------

    def _ensure_project(self) -> Project:
        if self._project is None:
            self._project = Project(
                name=self.export_step.project_name_edit.text().strip() or "Untitled Project",
                output_dir=Path(self.export_step.output_location_edit.text()),
            )
            self.export_step.project_name_edit.setText(self._project.name)
            self.save_project_button.setEnabled(True)
        return self._project

    def _sync_timeline_ui(self, *, selected_event_id: str | None = None) -> None:
        events = self._project.timeline_events if self._project is not None else []
        self.review_step.timeline_widget.set_events(
            events, selected_event_id=selected_event_id
        )
        self.review_step.set_max_timestamp(
            self.review_step.timeline_widget.effective_duration
        )
        self.review_step.set_selected_event(
            self.review_step.timeline_widget.selected_event()
        )
        self.review_step.update_event_summary(events)
        self._refresh_export_summary()

    def _refresh_export_summary(self) -> None:
        events = self._project.timeline_events if self._project is not None else []
        duration = (
            self._project.media_info.duration_seconds
            if self._project is not None and self._project.media_info is not None
            else self.review_step.timeline_widget.effective_duration
        )
        self.export_step.update_summary(events, duration)

    def _add_timeline_event_at_playhead(
        self, classification: EventClassification = EventClassification.KEYBOARD_TAP
    ) -> None:
        project = self._ensure_project()
        playhead = round(max(0.0, self.video_preview.current_seconds), 3)
        new_event = TimelineEvent(
            timestamp_seconds=playhead,
            classification=classification,
            enabled=True,
            source=EventSource.MANUAL,
            confidence=None,
            evidence="Added manually",
            intensity=0.75,
            variation=0.0,
            user_edited=True,
        )
        project.timeline_events.append(new_event)
        project.timeline_events.sort(
            key=lambda item: (item.timestamp_seconds, item.event_id)
        )
        project.touch()
        self._sync_timeline_ui(selected_event_id=new_event.event_id)
        self._set_friendly_status(
            f"Added {new_event.classification.label} at {playhead:.2f}s."
        )

    def _delete_timeline_event(self, event_id: str) -> None:
        if self._project is None:
            return
        before_count = len(self._project.timeline_events)
        self._project.timeline_events = [
            item for item in self._project.timeline_events if item.event_id != event_id
        ]
        if len(self._project.timeline_events) == before_count:
            return
        self._project.touch()
        self._sync_timeline_ui(selected_event_id=None)
        self._set_friendly_status("Removed selected sound event.")

    def _on_timeline_event_moved(self, event_id: str, new_timestamp: float) -> None:
        if self._project is None:
            return
        clamped_ts = round(max(0.0, float(new_timestamp)), 3)
        self._project.timeline_events = sorted(
            [
                replace(item, timestamp_seconds=clamped_ts, user_edited=True)
                if item.event_id == event_id
                else item
                for item in self._project.timeline_events
            ],
            key=lambda item: (item.timestamp_seconds, item.event_id),
        )
        self._project.touch()
        self._sync_timeline_ui(selected_event_id=event_id)

    def _on_inspector_event_modified(self, updated_event: TimelineEvent) -> None:
        if self._project is None:
            return
        edited = replace(updated_event, user_edited=True)
        self._project.timeline_events = sorted(
            [
                edited if item.event_id == edited.event_id else item
                for item in self._project.timeline_events
            ],
            key=lambda item: (item.timestamp_seconds, item.event_id),
        )
        self._project.touch()
        self._sync_timeline_ui(selected_event_id=edited.event_id)

    # ------------------------------------------------------------------
    # Sound Customization, Preview & Export
    # ------------------------------------------------------------------

    def _on_sound_profile_changed(self, profile: SoundProfile) -> None:
        self._sound_effects_service.sound_profile = profile

    def _on_preview_sample_requested(self, event_type: SoundEventType) -> None:
        try:
            self._sound_preview_service.preview_sound_event(
                SoundEvent(0.0, event_type, intensity=0.85, variation=0.0)
            )
        except (SoundPreviewError, ValueError) as exc:
            self.status_panel.warning(f"Sound preview failed: {exc}")
            self._set_friendly_status(
                "Could not play audio preview. Check your Windows audio output device.",
                level="warning",
                show_details=True,
            )

    def _on_preview_sound_requested(
        self, event: TimelineEvent, variation_override: float | None
    ) -> None:
        try:
            self._sound_preview_service.preview_timeline_event(
                event, variation_override=variation_override
            )
        except (SoundPreviewError, ValueError) as exc:
            self.status_panel.warning(f"Could not preview sound effect: {exc}")
            self._set_friendly_status(str(exc), level="warning")

    def _preview_timeline_mix(self) -> None:
        if self._project is None or not self._project.timeline_events:
            self._set_friendly_status(
                "Add or detect sounds on the Review tab before previewing.",
                level="warning",
            )
            return

        duration_seconds: float | None = None
        if (
            self._project.media_info is not None
            and self._project.media_info.duration_seconds is not None
        ):
            duration_seconds = self._project.media_info.duration_seconds
        elif self.review_step.timeline_widget.effective_duration > 0.0:
            duration_seconds = self.review_step.timeline_widget.effective_duration

        use_variation = self.sound_step.current_profile().human_variation
        try:
            self._sound_preview_service.preview_timeline_mix(
                self._project.timeline_events,
                duration_seconds=duration_seconds,
                variation=use_variation,
            )
        except (SoundPreviewError, ValueError) as exc:
            self.status_panel.warning(f"Could not preview timeline mix: {exc}")
            self._set_friendly_status(str(exc), level="warning")
            return

        self._set_friendly_status("Playing synchronized sound preview…", level="info")

    def _stop_sound_preview(self) -> None:
        self._sound_preview_service.stop()
        self._set_friendly_status("Audio preview stopped.")

    def _export_timeline_sounds(self) -> None:
        if self._project is None or not self._project.timeline_events:
            self._set_friendly_status(
                "No sounds to export yet. Detect activity or add events on the Review tab.",
                level="warning",
            )
            return

        events = timeline_events_to_sound_events(self._project.timeline_events)
        if not events:
            self._set_friendly_status(
                "All detected markers are uncertain or muted. Enable or reclassify them before exporting.",
                level="warning",
            )
            return

        duration_seconds: float | None = None
        if (
            self._project.media_info is not None
            and self._project.media_info.duration_seconds is not None
        ):
            duration_seconds = self._project.media_info.duration_seconds
        elif self.review_step.timeline_widget.effective_duration > 0.0:
            duration_seconds = self.review_step.timeline_widget.effective_duration

        self._render_sound_events_track(events, duration_seconds=duration_seconds)

    def _render_sound_events_track(
        self,
        events,
        *,
        duration_seconds: float | None,
    ) -> None:
        output_path = (
            Path(self.export_step.output_location_edit.text())
            / f"codesound-activity-{uuid4().hex}.wav"
        )
        use_variation = self.sound_step.current_profile().human_variation
        self.export_step.export_progress.show()
        try:
            generated_path = self._sound_effects_service.render(
                events,
                output_path,
                duration_seconds=duration_seconds,
                variation=use_variation,
            )
        except (OSError, ValueError) as exc:
            log.exception("Could not generate activity sound effects")
            self.status_panel.error(f"Could not export WAV audio: {exc}")
            self._set_friendly_status(
                "Could not export the audio file. Try choosing a different output folder.",
                level="error",
                show_details=True,
            )
            return
        finally:
            self.export_step.export_progress.hide()

        self.status_panel.success(f"Exported WAV audio: {generated_path}")
        self.export_step.show_export_success(generated_path)
        self._set_friendly_status("Audio exported successfully.", level="success")

    def _open_output_folder(self) -> None:
        folder = Path(self.export_step.output_location_edit.text())
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event) -> None:  # noqa: N802
        self._sound_preview_service.stop()
        self.video_preview.shutdown()
        activity_worker = self._activity_worker
        if activity_worker is not None and activity_worker.isRunning():
            activity_worker.cancel()
            activity_worker.wait()
        worker = self._probe_worker
        if worker is not None and worker.isRunning():
            worker.wait()
        event.accept()
