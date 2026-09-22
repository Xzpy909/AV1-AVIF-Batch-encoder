"""
settings_dialog.py - Settings Window for AV1 Batch Encoder
Supports Video & Photo SVT-AV1 configuration with .ini persistence.
"""

import os
import configparser
from pathlib import Path
from typing import Dict, Any

try:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
        QLabel, QComboBox, QSlider, QDoubleSpinBox, QSpinBox,
        QCheckBox, QPushButton, QGroupBox, QFormLayout, QMessageBox,
        QFileDialog
    )
    from PyQt6.QtCore import Qt
except ImportError:
    class QDialog:
        def __init__(self, parent=None): pass
        def exec(self): return 1
    class QWidget: pass


DEFAULT_VIDEO_CONFIG = {
    "tune": 1,
    "preset_le_1080p": 2,
    "preset_gt_1080p": 4,
    "crf_enabled": False,
    "crf": 35.0,
    "enable_dlf": True,
    "enable_tf": True,
    "enable_qmpsnr": True,
    "downscale_gt_1080p": False,
    "scale_filter": "spline36",
}
DEFAULT_PHOTO_CONFIG = {
    "qcolor": 50,              # avifenc -q,--qcolor      (0-100, default 50)
    "speed": 2,                # avifenc -s,--speed       (0-10, default 2)
    "yuv_format": "444",       # avifenc -y,--yuv         (444/422/420/400, default 444)
    "sharpness": 0,            # avifenc -a sharpness=S   (0-7, default 0)
    "tune": "iq",              # avifenc -a tune=METRIC   (psnr/ssim/iq, default iq -> flag omitted)
    "gain_map_mode": "auto",   # "auto" (avifenc embeds any gain map present in source), "sdr" (--ignore-gain-map)
    "qgain_map": 75,           # avifenc --qgain-map quality (0-100, default 75)
}

TUNE_OPTIONS = [
    (0, "0: VQ (Visual Quality)"),
    (1, "1: PSNR (Default Video)"),
    (2, "2: SSIM"),
    (3, "3: IQ (Image Quality - Default Photo)"),
    (4, "4: MS_SSIM (MS_SSIM & SSIMULACRA2)"),
    (5, "5: VMAF"),
    (6, "6: Film Grain"),
]

AVIF_TUNE_OPTIONS = [
    ("iq", "IQ - Image Quality (Default, flag omitted)"),
    ("psnr", "PSNR"),
    ("ssim", "SSIM"),
]

AVIF_YUV_FORMATS = [
    ("444", "444 (Default, highest color fidelity)"),
    ("422", "422"),
    ("420", "420 (smaller file size)"),
    ("400", "400 (grayscale)"),
    ("auto", "Auto (honor source format)"),
]

class ConfigManager:
    """Handles loading and saving settings to .ini configuration file."""

    @staticmethod
    def get_default_ini_path() -> str:
        return str(Path(__file__).resolve().parent / "config.ini")

    @classmethod
    def load_config(cls, ini_path: str = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        path = ini_path or cls.get_default_ini_path()
        video_cfg = dict(DEFAULT_VIDEO_CONFIG)
        photo_cfg = dict(DEFAULT_PHOTO_CONFIG)

        if not os.path.exists(path):
            return video_cfg, photo_cfg

        config = configparser.ConfigParser()
        try:
            config.read(path, encoding="utf-8")

            if config.has_section("Video"):
                v = config["Video"]
                video_cfg["tune"] = v.getint("tune", fallback=DEFAULT_VIDEO_CONFIG["tune"])
                video_cfg["preset_le_1080p"] = v.getint("preset_le_1080p", fallback=DEFAULT_VIDEO_CONFIG["preset_le_1080p"])
                video_cfg["preset_gt_1080p"] = v.getint("preset_gt_1080p", fallback=DEFAULT_VIDEO_CONFIG["preset_gt_1080p"])
                video_cfg["crf_enabled"] = v.getboolean("crf_enabled", fallback=DEFAULT_VIDEO_CONFIG["crf_enabled"])
                video_cfg["crf"] = v.getfloat("crf", fallback=DEFAULT_VIDEO_CONFIG["crf"])
                video_cfg["enable_dlf"] = v.getboolean("enable_dlf", fallback=DEFAULT_VIDEO_CONFIG["enable_dlf"])
                video_cfg["enable_tf"] = v.getboolean("enable_tf", fallback=DEFAULT_VIDEO_CONFIG["enable_tf"])
                video_cfg["enable_qmpsnr"] = v.getboolean("enable_qmpsnr", fallback=DEFAULT_VIDEO_CONFIG["enable_qmpsnr"])
                video_cfg["downscale_gt_1080p"] = v.getboolean("downscale_gt_1080p", fallback=DEFAULT_VIDEO_CONFIG["downscale_gt_1080p"])
                video_cfg["scale_filter"] = v.get("scale_filter", fallback=DEFAULT_VIDEO_CONFIG["scale_filter"])

            if config.has_section("Photo"):
                p = config["Photo"]
                photo_cfg["qcolor"] = p.getint("qcolor", fallback=DEFAULT_PHOTO_CONFIG["qcolor"])
                photo_cfg["speed"] = p.getint("speed", fallback=DEFAULT_PHOTO_CONFIG["speed"])
                photo_cfg["yuv_format"] = p.get("yuv_format", fallback=DEFAULT_PHOTO_CONFIG["yuv_format"])
                photo_cfg["sharpness"] = p.getint("sharpness", fallback=DEFAULT_PHOTO_CONFIG["sharpness"])
                photo_cfg["tune"] = p.get("tune", fallback=DEFAULT_PHOTO_CONFIG["tune"])
                photo_cfg["gain_map_mode"] = p.get("gain_map_mode", fallback=DEFAULT_PHOTO_CONFIG["gain_map_mode"])
                photo_cfg["qgain_map"] = p.getint("qgain_map", fallback=DEFAULT_PHOTO_CONFIG["qgain_map"])
        except Exception as e:
            print(f"[ConfigManager] Error reading config file {path}: {e}")

        return video_cfg, photo_cfg

    @classmethod
    def save_config(cls, video_cfg: Dict[str, Any], photo_cfg: Dict[str, Any], ini_path: str = None) -> bool:
        path = ini_path or cls.get_default_ini_path()
        config = configparser.ConfigParser()

        config["Video"] = {
            "tune": str(video_cfg.get("tune", 1)),
            "preset_le_1080p": str(video_cfg.get("preset_le_1080p", 2)),
            "preset_gt_1080p": str(video_cfg.get("preset_gt_1080p", 4)),
            "crf_enabled": str(video_cfg.get("crf_enabled", False)).lower(),
            "crf": str(video_cfg.get("crf", 35.0)),
            "enable_dlf": str(video_cfg.get("enable_dlf", True)).lower(),
            "enable_tf": str(video_cfg.get("enable_tf", True)).lower(),
            "enable_qmpsnr": str(video_cfg.get("enable_qmpsnr", True)).lower(),
            "downscale_gt_1080p": str(video_cfg.get("downscale_gt_1080p", False)).lower(),
            "scale_filter": str(video_cfg.get("scale_filter", "spline36")),
        }

        config["Photo"] = {
            "qcolor": str(photo_cfg.get("qcolor", 50)),
            "speed": str(photo_cfg.get("speed", 2)),
            "yuv_format": str(photo_cfg.get("yuv_format", "444")),
            "sharpness": str(photo_cfg.get("sharpness", 0)),
            "tune": str(photo_cfg.get("tune", "iq")),
            "gain_map_mode": str(photo_cfg.get("gain_map_mode", "auto")),
            "qgain_map": str(photo_cfg.get("qgain_map", 75)),
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                config.write(f)
            return True
        except Exception as e:
            print(f"[ConfigManager] Error writing config to {path}: {e}")
            return False


class SettingsDialog(QDialog):
    """
    Settings window with Video and Photo tabs, dynamic UI controls,
    and .ini file persistence.
    """
    def __init__(self, parent=None, ini_path: str = None):
        super().__init__(parent)
        self.ini_path = ini_path or ConfigManager.get_default_ini_path()
        self.setWindowTitle("Encoding Settings")
        
        # Increased resolution to give inputs and controls room to breathe
        self.resize(680, 680)
        self.setMinimumSize(600, 600)

        self._apply_stylesheet()

        # Load initial values
        self.video_settings, self.photo_settings = ConfigManager.load_config(self.ini_path)

        self._init_ui()
        self._load_values_to_ui()

    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #e0e0e0;
            }
            QTabWidget::pane {
                border: 1px solid #333333;
                background-color: #252526;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #2d2d2d;
                color: #aaaaaa;
                padding: 8px 18px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #252526;
                color: #ffffff;
                font-weight: bold;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                margin-top: 14px;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 6px;
                color: #3b82f6;
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                min-height: 28px;
                padding: 2px 8px;
                border: 1px solid #454545;
                border-radius: 4px;
                background-color: #2a2a2a;
                color: #ffffff;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QCheckBox {
                spacing: 8px;
                color: #e0e0e0;
            }
            QLabel {
                color: #cccccc;
            }
        """)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Video Tab
        self.video_tab = QWidget()
        self._build_video_tab()
        self.tab_widget.addTab(self.video_tab, "Video Encoding")

        # Photo Tab
        self.photo_tab = QWidget()
        self._build_photo_tab()
        self.tab_widget.addTab(self.photo_tab, "Photo Encoding")

        # Footer Actions
        footer_layout = QHBoxLayout()
        btn_style_secondary = """
            QPushButton {
                padding: 7px 14px;
                font-size: 12px;
                color: #ffffff;
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #475569;
                border-color: #64748b;
            }
            QPushButton:pressed {
                background-color: #1e293b;
            }
        """

        self.btn_load_ini = QPushButton("Load from .ini")
        self.btn_load_ini.setStyleSheet(btn_style_secondary)
        self.btn_load_ini.clicked.connect(self._on_load_ini_clicked)

        self.btn_save_ini = QPushButton("Save to .ini")
        self.btn_save_ini.setStyleSheet(btn_style_secondary)
        self.btn_save_ini.clicked.connect(self._on_save_ini_clicked)

        self.btn_defaults = QPushButton("Reset Defaults")
        self.btn_defaults.setStyleSheet(btn_style_secondary)
        self.btn_defaults.clicked.connect(self._on_reset_defaults_clicked)

        footer_layout.addWidget(self.btn_load_ini)
        footer_layout.addWidget(self.btn_save_ini)
        footer_layout.addWidget(self.btn_defaults)
        footer_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                padding: 7px 14px;
                font-size: 12px;
                color: #cbd5e1;
                background-color: transparent;
                border: 1px solid #475569;
                border-radius: 4px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #334155;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)

        # Removed raw underscores that were causing mnemonics/label shortcuts to display awkwardly
        self.btn_ok = QPushButton("Save & Apply")
        self.btn_ok.setDefault(True)
        self.btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                padding: 7px 18px;
                border: 1px solid #1d4ed8;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
        """)
        self.btn_ok.clicked.connect(self._on_accept)

        footer_layout.addWidget(self.btn_cancel)
        footer_layout.addWidget(self.btn_ok)

        main_layout.addLayout(footer_layout)

    def _build_video_tab(self):
        layout = QVBoxLayout(self.video_tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Optimization & Presets Group
        grp_speed = QGroupBox("Optimization & Presets")
        form_speed = QFormLayout(grp_speed)
        form_speed.setSpacing(12)
        form_speed.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.v_tune_combo = QComboBox()
        for val, label in TUNE_OPTIONS:
            self.v_tune_combo.addItem(label, val)
        form_speed.addRow("Tune Metric (--tune):", self.v_tune_combo)

        self.v_preset_le_combo = QComboBox()
        for p in range(1, 9):
            self.v_preset_le_combo.addItem(f"Preset {p}", p)
        form_speed.addRow("Speed for <= 1080p (Default 2):", self.v_preset_le_combo)

        self.v_preset_gt_combo = QComboBox()
        for p in range(1, 9):
            self.v_preset_gt_combo.addItem(f"Preset {p}", p)
        form_speed.addRow("Speed for > 1080p (Default 4):", self.v_preset_gt_combo)

        layout.addWidget(grp_speed)

        # Rate Control Group
        grp_rc = QGroupBox("Rate Control")
        vbox_rc = QVBoxLayout(grp_rc)
        vbox_rc.setSpacing(10)

        self.v_crf_checkbox = QCheckBox("Specify Custom CRF (--crf) [Default: disabled, decided by encoder]")
        self.v_crf_checkbox.toggled.connect(self._on_crf_toggled)
        vbox_rc.addWidget(self.v_crf_checkbox)

        h_crf = QHBoxLayout()
        self.v_crf_slider = QSlider(Qt.Orientation.Horizontal)
        self.v_crf_slider.setRange(4, 280)
        self.v_crf_slider.setSingleStep(1)
        self.v_crf_slider.setPageStep(4)

        self.v_crf_spin = QDoubleSpinBox()
        self.v_crf_spin.setRange(1.0, 70.0)
        self.v_crf_spin.setSingleStep(0.25)
        self.v_crf_spin.setDecimals(2)
        self.v_crf_spin.setValue(35.0)

        self.v_crf_slider.valueChanged.connect(lambda v: self.v_crf_spin.setValue(v * 0.25))
        self.v_crf_spin.valueChanged.connect(lambda val: self.v_crf_slider.setValue(int(round(val / 0.25))))

        h_crf.addWidget(self.v_crf_slider)
        h_crf.addWidget(self.v_crf_spin)
        vbox_rc.addLayout(h_crf)
        layout.addWidget(grp_rc)

        # Advanced Filters Group
        grp_flags = QGroupBox("Advanced Filters & Psychovisual Flags")
        vbox_flags = QVBoxLayout(grp_flags)
        vbox_flags.setSpacing(8)

        self.v_chk_dlf = QCheckBox("Enable Deblocking Loop Filter (--enable-dlf 2)")
        self.v_chk_tf = QCheckBox("Enable ALT-REF Temporally Filtered Frames (--enable-tf 2)")
        self.v_chk_qmpsnr = QCheckBox("Enable QM-PSNR Distortion Metric (--enable-qmpsnr 1)")

        vbox_flags.addWidget(self.v_chk_dlf)
        vbox_flags.addWidget(self.v_chk_tf)
        vbox_flags.addWidget(self.v_chk_qmpsnr)
        layout.addWidget(grp_flags)

        # Downscaling Group
        grp_scale = QGroupBox("Downscaling Options")
        vbox_scale = QVBoxLayout(grp_scale)
        vbox_scale.setSpacing(10)

        self.v_chk_downscale = QCheckBox("Downscale videos > 1080p to 1080p")
        vbox_scale.addWidget(self.v_chk_downscale)

        form_scale = QFormLayout()
        form_scale.setSpacing(10)
        form_scale.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.v_filter_combo = QComboBox()
        self.v_filter_combo.addItem("zscale (Spline36)", "spline36")
        self.v_filter_combo.addItem("zscale (Lanczos)", "lanczos")
        self.v_filter_combo.addItem("swscale (Spline)", "swscale_spline")
        form_scale.addRow("Scaling Filter Algorithm:", self.v_filter_combo)

        vbox_scale.addLayout(form_scale)
        layout.addWidget(grp_scale)

        layout.addStretch()

    def _build_photo_tab(self):
        layout = QVBoxLayout(self.photo_tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        grp_basics = QGroupBox("AVIF Encoding (avifenc.exe)")
        form_basics = QFormLayout(grp_basics)
        form_basics.setSpacing(10)
        form_basics.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.p_qcolor_spin = QSpinBox()
        self.p_qcolor_spin.setRange(0, 100)
        self.p_qcolor_spin.setValue(50)
        self.p_qcolor_spin.setToolTip("Quality for color in 0..100 where 100 is lossless (default 50)")
        form_basics.addRow("Color Quality (-q, --qcolor):", self.p_qcolor_spin)

        self.p_speed_spin = QSpinBox()
        self.p_speed_spin.setRange(0, 10)
        self.p_speed_spin.setValue(2)
        self.p_speed_spin.setToolTip("Encoder speed in 0..10 where 0 is the slowest, 10 is the fastest (default 2)")
        form_basics.addRow("Speed (-s, --speed):", self.p_speed_spin)

        self.p_yuv_combo = QComboBox()
        for val, label in AVIF_YUV_FORMATS:
            self.p_yuv_combo.addItem(label, val)
        form_basics.addRow("Chroma Subsampling (-y, --yuv):", self.p_yuv_combo)

        layout.addWidget(grp_basics)

        grp_advanced = QGroupBox("Advanced Codec Options")
        form_advanced = QFormLayout(grp_advanced)
        form_advanced.setSpacing(10)
        form_advanced.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.p_sharpness_spin = QSpinBox()
        self.p_sharpness_spin.setRange(0, 7)
        self.p_sharpness_spin.setValue(0)
        self.p_sharpness_spin.setToolTip("Bias towards block sharpness in rate-distortion optimization (0..7, default 0)")
        form_advanced.addRow("Sharpness (-a sharpness=S):", self.p_sharpness_spin)

        self.p_avif_tune_combo = QComboBox()
        for val, label in AVIF_TUNE_OPTIONS:
            self.p_avif_tune_combo.addItem(label, val)
        self.p_avif_tune_combo.setToolTip("Tune the encoder for a distortion metric (default IQ; the -a tune= flag is omitted when set to IQ)")
        form_advanced.addRow("Tune Metric (-a tune=METRIC):", self.p_avif_tune_combo)

        layout.addWidget(grp_advanced)

        grp_color = QGroupBox("Ultra HDR Gain Map")
        form_color = QFormLayout(grp_color)
        form_color.setSpacing(10)
        form_color.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.p_gain_map_combo = QComboBox()
        self.p_gain_map_combo.addItem("Auto (embed gain map natively if source has one)", "auto")
        self.p_gain_map_combo.addItem("Clean SDR AVIF (--ignore-gain-map)", "sdr")
        form_color.addRow("Ultra HDR Gain Map Handling:", self.p_gain_map_combo)

        self.p_qgain_map_spin = QSpinBox()
        self.p_qgain_map_spin.setRange(0, 100)
        self.p_qgain_map_spin.setValue(75)
        self.p_qgain_map_spin.setToolTip("Quality for the gain map in 0..100 where 100 is lossless (avifenc --qgain-map, default 75)")
        form_color.addRow("Gain Map Quality (--qgain-map):", self.p_qgain_map_spin)

        layout.addWidget(grp_color)

        layout.addStretch()

    def _on_crf_toggled(self, checked: bool):
        self.v_crf_slider.setEnabled(checked)
        self.v_crf_spin.setEnabled(checked)

    def _load_values_to_ui(self):
        idx = self.v_tune_combo.findData(self.video_settings.get("tune", 1))
        if idx >= 0: self.v_tune_combo.setCurrentIndex(idx)

        idx_le = self.v_preset_le_combo.findData(self.video_settings.get("preset_le_1080p", 2))
        if idx_le >= 0: self.v_preset_le_combo.setCurrentIndex(idx_le)

        idx_gt = self.v_preset_gt_combo.findData(self.video_settings.get("preset_gt_1080p", 4))
        if idx_gt >= 0: self.v_preset_gt_combo.setCurrentIndex(idx_gt)

        crf_on = self.video_settings.get("crf_enabled", False)
        self.v_crf_checkbox.setChecked(crf_on)
        self.v_crf_spin.setValue(float(self.video_settings.get("crf", 35.0)))
        self._on_crf_toggled(crf_on)

        self.v_chk_dlf.setChecked(self.video_settings.get("enable_dlf", True))
        self.v_chk_tf.setChecked(self.video_settings.get("enable_tf", True))
        self.v_chk_qmpsnr.setChecked(self.video_settings.get("enable_qmpsnr", True))

        self.v_chk_downscale.setChecked(self.video_settings.get("downscale_gt_1080p", False))
        idx_filter = self.v_filter_combo.findData(self.video_settings.get("scale_filter", "spline36"))
        if idx_filter >= 0:
            self.v_filter_combo.setCurrentIndex(idx_filter)

        self.p_qcolor_spin.setValue(int(self.photo_settings.get("qcolor", 50)))
        self.p_speed_spin.setValue(int(self.photo_settings.get("speed", 2)))

        idx_yuv = self.p_yuv_combo.findData(str(self.photo_settings.get("yuv_format", "444")))
        if idx_yuv >= 0: self.p_yuv_combo.setCurrentIndex(idx_yuv)

        self.p_sharpness_spin.setValue(int(self.photo_settings.get("sharpness", 0)))

        idx_tune = self.p_avif_tune_combo.findData(str(self.photo_settings.get("tune", "iq")))
        if idx_tune >= 0: self.p_avif_tune_combo.setCurrentIndex(idx_tune)

        idx_gm = self.p_gain_map_combo.findData(str(self.photo_settings.get("gain_map_mode", "auto")))
        if idx_gm >= 0: self.p_gain_map_combo.setCurrentIndex(idx_gm)

        self.p_qgain_map_spin.setValue(int(self.photo_settings.get("qgain_map", 75)))

    def get_settings(self) -> tuple[Dict[str, Any], Dict[str, Any]]:
        video = {
            "tune": self.v_tune_combo.currentData(),
            "preset_le_1080p": self.v_preset_le_combo.currentData(),
            "preset_gt_1080p": self.v_preset_gt_combo.currentData(),
            "crf_enabled": self.v_crf_checkbox.isChecked(),
            "crf": round(self.v_crf_spin.value(), 2),
            "enable_dlf": self.v_chk_dlf.isChecked(),
            "enable_tf": self.v_chk_tf.isChecked(),
            "enable_qmpsnr": self.v_chk_qmpsnr.isChecked(),
            "downscale_gt_1080p": self.v_chk_downscale.isChecked(),
            "scale_filter": self.v_filter_combo.currentData(),
        }

        photo = {
            "qcolor": self.p_qcolor_spin.value(),
            "speed": self.p_speed_spin.value(),
            "yuv_format": self.p_yuv_combo.currentData(),
            "sharpness": self.p_sharpness_spin.value(),
            "tune": self.p_avif_tune_combo.currentData(),
            "gain_map_mode": self.p_gain_map_combo.currentData(),
            "qgain_map": self.p_qgain_map_spin.value(),
        }
        return video, photo

    def _on_accept(self):
        v, p = self.get_settings()
        self.video_settings = v
        self.photo_settings = p
        ConfigManager.save_config(v, p, self.ini_path)
        self.accept()

    def _on_save_ini_clicked(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Settings to INI", self.ini_path, "INI files (*.ini)")
        if file_path:
            v, p = self.get_settings()
            if ConfigManager.save_config(v, p, file_path):
                QMessageBox.information(self, "Saved", f"Settings saved to {file_path}")

    def _on_load_ini_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Settings from INI", self.ini_path, "INI files (*.ini)")
        if file_path and os.path.exists(file_path):
            self.video_settings, self.photo_settings = ConfigManager.load_config(file_path)
            self._load_values_to_ui()
            QMessageBox.information(self, "Loaded", f"Settings loaded from {file_path}")

    def _on_reset_defaults_clicked(self):
        self.video_settings = dict(DEFAULT_VIDEO_CONFIG)
        self.photo_settings = dict(DEFAULT_PHOTO_CONFIG)
        self._load_values_to_ui()