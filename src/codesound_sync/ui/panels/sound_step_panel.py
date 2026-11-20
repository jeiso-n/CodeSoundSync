"""Step 3 (SOUND): Presets, keyboard/mouse sound styles, volume, and mix preview."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from codesound_sync.models.sound_event import SoundEventType
from codesound_sync.services.sound_generator import (
    KeyboardSoundStyle,
    MouseSoundStyle,
    SoundProfile,
)


class SoundStepPanel(QWidget):
    """Third workflow step: customize sound styles, volumes, and audition the mix."""

    profile_changed = Signal(object)  # SoundProfile
    preview_sample_requested = Signal(object)  # SoundEventType
    preview_mix_requested = Signal()
    stop_audio_requested = Signal()
    continue_to_export_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("soundStepPanel")
        self._updating = False
        self._build_ui()
        self._emit_profile()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Presets bar
        presets_card = QFrame()
        presets_card.setObjectName("surfaceCard")
        presets_layout = QHBoxLayout(presets_card)
        presets_layout.setContentsMargins(16, 12, 16, 12)
        presets_layout.setSpacing(10)

        preset_title = QLabel("Quick Presets:")
        preset_title.setObjectName("sectionTitle")
        presets_layout.addWidget(preset_title)

        self.preset_crisp_button = QPushButton("Crisp Mechanical")
        self.preset_crisp_button.clicked.connect(
            lambda: self.apply_preset(
                KeyboardSoundStyle.MECHANICAL_CRISP,
                MouseSoundStyle.CRISP_SWITCH,
                keyboard_pct=85,
                mouse_pct=80,
                variation=True,
            )
        )
        presets_layout.addWidget(self.preset_crisp_button)

        self.preset_laptop_button = QPushButton("Soft Laptop")
        self.preset_laptop_button.clicked.connect(
            lambda: self.apply_preset(
                KeyboardSoundStyle.SOFT_LAPTOP,
                MouseSoundStyle.SOFT_CLICK,
                keyboard_pct=70,
                mouse_pct=65,
                variation=True,
            )
        )
        presets_layout.addWidget(self.preset_laptop_button)

        self.preset_studio_button = QPushButton("Podcast Studio")
        self.preset_studio_button.clicked.connect(
            lambda: self.apply_preset(
                KeyboardSoundStyle.WARM_STUDIO,
                MouseSoundStyle.SOFT_CLICK,
                keyboard_pct=80,
                mouse_pct=75,
                variation=True,
            )
        )
        presets_layout.addWidget(self.preset_studio_button)
        presets_layout.addStretch()
        layout.addWidget(presets_card)

        # Two-column Keyboard & Mouse cards
        columns = QHBoxLayout()
        columns.setSpacing(12)

        # Keyboard Card
        kb_card = QFrame()
        kb_card.setObjectName("surfaceCard")
        kb_layout = QVBoxLayout(kb_card)
        kb_layout.setContentsMargins(18, 16, 18, 16)
        kb_layout.setSpacing(10)

        kb_title = QLabel("Keyboard Sounds")
        kb_title.setObjectName("sectionTitle")
        kb_layout.addWidget(kb_title)

        self.keyboard_style_combo = QComboBox()
        for style in KeyboardSoundStyle:
            self.keyboard_style_combo.addItem(style.label, style.value)
        self.keyboard_style_combo.currentIndexChanged.connect(self._on_controls_changed)
        kb_layout.addWidget(self.keyboard_style_combo)

        self.keyboard_desc_label = QLabel(KeyboardSoundStyle.MECHANICAL_CRISP.description)
        self.keyboard_desc_label.setObjectName("mutedText")
        self.keyboard_desc_label.setWordWrap(True)
        kb_layout.addWidget(self.keyboard_desc_label)

        kb_vol_row = QHBoxLayout()
        kb_vol_row.addWidget(QLabel("Volume:"))
        self.keyboard_volume_slider = QSlider(Qt.Horizontal)
        self.keyboard_volume_slider.setRange(0, 100)
        self.keyboard_volume_slider.setValue(85)
        self.keyboard_volume_slider.valueChanged.connect(self._on_controls_changed)
        kb_vol_row.addWidget(self.keyboard_volume_slider, 1)
        self.keyboard_volume_label = QLabel("85%")
        self.keyboard_volume_label.setMinimumWidth(38)
        kb_vol_row.addWidget(self.keyboard_volume_label)
        kb_layout.addLayout(kb_vol_row)

        self.preview_keyboard_button = QPushButton("Preview Key Sound")
        self.preview_keyboard_button.clicked.connect(
            lambda: self.preview_sample_requested.emit(SoundEventType.KEYBOARD_TAP)
        )
        kb_layout.addWidget(self.preview_keyboard_button)
        kb_layout.addStretch()
        columns.addWidget(kb_card, 1)

        # Mouse Card
        mouse_card = QFrame()
        mouse_card.setObjectName("surfaceCard")
        mouse_layout = QVBoxLayout(mouse_card)
        mouse_layout.setContentsMargins(18, 16, 18, 16)
        mouse_layout.setSpacing(10)

        mouse_title = QLabel("Mouse Click Sounds")
        mouse_title.setObjectName("sectionTitle")
        mouse_layout.addWidget(mouse_title)

        self.mouse_style_combo = QComboBox()
        for style in MouseSoundStyle:
            self.mouse_style_combo.addItem(style.label, style.value)
        self.mouse_style_combo.currentIndexChanged.connect(self._on_controls_changed)
        mouse_layout.addWidget(self.mouse_style_combo)

        self.mouse_desc_label = QLabel(MouseSoundStyle.CRISP_SWITCH.description)
        self.mouse_desc_label.setObjectName("mutedText")
        self.mouse_desc_label.setWordWrap(True)
        mouse_layout.addWidget(self.mouse_desc_label)

        mouse_vol_row = QHBoxLayout()
        mouse_vol_row.addWidget(QLabel("Volume:"))
        self.mouse_volume_slider = QSlider(Qt.Horizontal)
        self.mouse_volume_slider.setRange(0, 100)
        self.mouse_volume_slider.setValue(80)
        self.mouse_volume_slider.valueChanged.connect(self._on_controls_changed)
        mouse_vol_row.addWidget(self.mouse_volume_slider, 1)
        self.mouse_volume_label = QLabel("80%")
        self.mouse_volume_label.setMinimumWidth(38)
        mouse_vol_row.addWidget(self.mouse_volume_label)
        mouse_layout.addLayout(mouse_vol_row)

        mouse_btns = QHBoxLayout()
        self.preview_left_click_button = QPushButton("Preview Left Click")
        self.preview_left_click_button.clicked.connect(
            lambda: self.preview_sample_requested.emit(SoundEventType.MOUSE_LEFT_CLICK)
        )
        self.preview_right_click_button = QPushButton("Preview Right Click")
        self.preview_right_click_button.clicked.connect(
            lambda: self.preview_sample_requested.emit(SoundEventType.MOUSE_RIGHT_CLICK)
        )
        mouse_btns.addWidget(self.preview_left_click_button)
        mouse_btns.addWidget(self.preview_right_click_button)
        mouse_layout.addLayout(mouse_btns)
        mouse_layout.addStretch()
        columns.addWidget(mouse_card, 1)

        layout.addLayout(columns)

        # Natural variation + full mix preview footer
        footer_card = QFrame()
        footer_card.setObjectName("surfaceCard")
        footer_layout = QHBoxLayout(footer_card)
        footer_layout.setContentsMargins(18, 14, 18, 14)
        footer_layout.setSpacing(12)

        var_col = QVBoxLayout()
        var_col.setSpacing(2)
        self.variation_checkbox = QCheckBox("Natural Human Variation")
        self.variation_checkbox.setChecked(True)
        self.variation_checkbox.toggled.connect(self._on_controls_changed)
        var_desc = QLabel(
            "Subtly varies each keystroke's pitch and timing so typing sounds natural instead of repetitive."
        )
        var_desc.setObjectName("mutedText")
        var_desc.setWordWrap(True)
        var_col.addWidget(self.variation_checkbox)
        var_col.addWidget(var_desc)
        footer_layout.addLayout(var_col, 1)

        self.preview_mix_button = QPushButton("Preview Full Mix")
        self.preview_mix_button.setMinimumHeight(38)
        self.preview_mix_button.clicked.connect(self.preview_mix_requested.emit)
        footer_layout.addWidget(self.preview_mix_button)

        self.stop_audio_button = QPushButton("Stop")
        self.stop_audio_button.setMinimumHeight(38)
        self.stop_audio_button.clicked.connect(self.stop_audio_requested.emit)
        footer_layout.addWidget(self.stop_audio_button)

        self.next_export_button = QPushButton("Continue to Export →")
        self.next_export_button.setObjectName("primaryActionButton")
        self.next_export_button.setMinimumHeight(38)
        self.next_export_button.clicked.connect(self.continue_to_export_requested.emit)
        footer_layout.addWidget(self.next_export_button)

        layout.addWidget(footer_card)
        layout.addStretch(1)

    def current_profile(self) -> SoundProfile:
        kb_style = KeyboardSoundStyle(self.keyboard_style_combo.currentData())
        mouse_style = MouseSoundStyle(self.mouse_style_combo.currentData())
        return SoundProfile(
            keyboard_style=kb_style,
            mouse_style=mouse_style,
            keyboard_volume=self.keyboard_volume_slider.value() / 100.0,
            mouse_volume=self.mouse_volume_slider.value() / 100.0,
            human_variation=self.variation_checkbox.isChecked(),
        )

    def apply_preset(
        self,
        kb_style: KeyboardSoundStyle,
        mouse_style: MouseSoundStyle,
        *,
        keyboard_pct: int,
        mouse_pct: int,
        variation: bool,
    ) -> None:
        self._updating = True
        try:
            kb_idx = self.keyboard_style_combo.findData(kb_style.value)
            if kb_idx >= 0:
                self.keyboard_style_combo.setCurrentIndex(kb_idx)
            m_idx = self.mouse_style_combo.findData(mouse_style.value)
            if m_idx >= 0:
                self.mouse_style_combo.setCurrentIndex(m_idx)
            self.keyboard_volume_slider.setValue(keyboard_pct)
            self.mouse_volume_slider.setValue(mouse_pct)
            self.variation_checkbox.setChecked(variation)
        finally:
            self._updating = False
        self._on_controls_changed()

    def _on_controls_changed(self) -> None:
        if self._updating:
            return
        profile = self.current_profile()
        self.keyboard_desc_label.setText(profile.keyboard_style.description)
        self.mouse_desc_label.setText(profile.mouse_style.description)
        self.keyboard_volume_label.setText(f"{self.keyboard_volume_slider.value()}%")
        self.mouse_volume_label.setText(f"{self.mouse_volume_slider.value()}%")
        self.profile_changed.emit(profile)

    def _emit_profile(self) -> None:
        self._on_controls_changed()
