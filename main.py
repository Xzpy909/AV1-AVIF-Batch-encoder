"""
main.py - Main Qt6 Application for AV1 Batch Encoder
Drag-and-Drop GUI, Job List with progress bars, Settings window,
and dynamic multi-state Start / Cancel Batch button.
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QLabel, QFileDialog, QPlainTextEdit, QSplitter,
    QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, QUrl, pyqtSlot
from PyQt6.QtGui import QIcon, QFont, QColor, QDragEnterEvent, QDropEvent

from encoder import MediaProbe, BatchWorker, resolve_tool_path, CommandBuilder
from settings_dialog import SettingsDialog, ConfigManager

# Custom Stylesheets for Start / Cancel button states:
# "same button just different states, blue ready, green on hover, green processing, red on hover for cancellation"
STYLE_READY = """
QPushButton#batch_btn {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: bold;
    font-size: 14px;
    padding: 9px 24px;
    border-radius: 6px;
    border: 1px solid #1d4ed8;
}
QPushButton#batch_btn:hover {
    background-color: #16a34a;
    border-color: #15803d;
}
QPushButton#batch_btn:pressed {
    background-color: #15803d;
}
QPushButton#batch_btn:disabled {
    background-color: #94a3b8;
    border-color: #cbd5e1;
    color: #f1f5f9;
}
"""

STYLE_PROCESSING = """
QPushButton#batch_btn {
    background-color: #16a34a;
    color: #ffffff;
    font-weight: bold;
    font-size: 14px;
    padding: 9px 24px;
    border-radius: 6px;
    border: 1px solid #15803d;
}
QPushButton#batch_btn:hover {
    background-color: #dc2626;
    border-color: #b91c1c;
}
QPushButton#batch_btn:pressed {
    background-color: #991b1b;
}
"""

SUPPORTED_EXTS = {
    # Video
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts", ".m4v", ".flv", ".wmv",
    # Photo
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".heic"
}


class DropTableWidget(QTableWidget):
    """QTableWidget subclass supporting drag-and-drop of files and folders."""
    def __init__(self, main_window: 'MainWindow', parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            self.main_window.add_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class MainWindow(QMainWindow):
    """Main window for AV1 Batch Encoder."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AV1 Batch Encoder (SVT-AV1 10-bit & FFmpeg)")
        self.resize(1020, 680)
        self.setMinimumSize(850, 520)

        # Load initial settings from config.ini
        self.video_settings, self.photo_settings = ConfigManager.load_config()

        # Batch state
        self.jobs: List[Dict[str, Any]] = []
        self.worker: BatchWorker = None
        self.is_processing = False

        self._init_ui()
        self._check_tools()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # Top Action Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.btn_add_files = QPushButton("Add Files...")
        self.btn_add_files.setStyleSheet("""
            QPushButton {
                padding: 7px 14px;
                font-weight: 500;
                font-size: 12px;
                color: #ffffff;
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #475569;
            }
            QPushButton:pressed {
                background-color: #0f172a;
            }
        """)
        self.btn_add_files.clicked.connect(self._on_add_files)

        self.btn_add_folder = QPushButton("Add Folder...")
        self.btn_add_folder.setStyleSheet("""
            QPushButton {
                padding: 7px 14px;
                font-weight: 500;
                font-size: 12px;
                color: #ffffff;
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #475569;
            }
            QPushButton:pressed {
                background-color: #0f172a;
            }
        """)
        self.btn_add_folder.clicked.connect(self._on_add_folder)

        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setStyleSheet("""
            QPushButton {
                padding: 7px 14px;
                font-size: 12px;
                color: #94a3b8;
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 5px;
            }
            QPushButton:hover {
                color: #ef4444;
                border-color: #ef4444;
                background-color: #1e1b4b;
            }
            QPushButton:pressed {
                background-color: #0f172a;
            }
        """)
        self.btn_clear.clicked.connect(self._on_clear_jobs)

        top_bar.addWidget(self.btn_add_files)
        top_bar.addWidget(self.btn_add_folder)
        top_bar.addWidget(self.btn_clear)
        top_bar.addStretch()

        # Settings button: opens settings window
        # Fix: Explicit dark slate background with clear white text and visible borders
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.setStyleSheet("""
            QPushButton {
                padding: 7px 18px;
                font-weight: 600;
                font-size: 12px;
                color: #ffffff;
                background-color: #334155;
                border: 1px solid #64748b;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #475569;
                color: #ffffff;
                border-color: #94a3b8;
            }
            QPushButton:pressed {
                background-color: #1e293b;
                color: #f8fafc;
            }
        """)
        self.btn_settings.clicked.connect(self._on_open_settings)
        top_bar.addWidget(self.btn_settings)

        # Start / Cancel Batch button
        # "same button just different states, blue ready, green on hover, green processing, red on hover for cancellation"
        self.btn_batch = QPushButton("Start Batch")
        self.btn_batch.setObjectName("batch_btn")
        self.btn_batch.setStyleSheet(STYLE_READY)
        self.btn_batch.clicked.connect(self._on_batch_button_clicked)
        top_bar.addWidget(self.btn_batch)

        root_layout.addLayout(top_bar)

        # Main splitter (Job table on top, Live Logs on bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Table Widget
        self.table = DropTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Source File", "Type", "Resolution", "Size", "Progress", "Status"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 180)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)

        splitter.addWidget(self.table)

        # Log Console Widget
        log_container = QWidget()
        log_vbox = QVBoxLayout(log_container)
        log_vbox.setContentsMargins(0, 4, 0, 0)
        log_vbox.setSpacing(4)

        log_hdr = QHBoxLayout()
        lbl_log = QLabel("Encoding Pipeline Log & Diagnostics:")
        lbl_log.setStyleSheet("font-weight: 600; color: #475569; font-size: 12px;")
        btn_clear_log = QPushButton("Clear Log")
        btn_clear_log.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn_clear_log.clicked.connect(lambda: self.log_view.clear())
        log_hdr.addWidget(lbl_log)
        log_hdr.addStretch()
        log_hdr.addWidget(btn_clear_log)
        log_vbox.addLayout(log_hdr)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-family: monospace; font-size: 12px;")
        log_vbox.addWidget(self.log_view)

        splitter.addWidget(log_container)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        root_layout.addWidget(splitter)

        # Bottom Overall Progress Bar & Status
        bottom_bar = QVBoxLayout()
        bottom_bar.setSpacing(4)

        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                text-align: center;
                height: 18px;
                background-color: #f8fafc;
            }
            QProgressBar::chunk {
                background-color: #2563eb;
                border-radius: 3px;
            }
        """)

        status_bar = QHBoxLayout()
        self.lbl_status = QLabel("Ready. Drag and drop media files or click 'Add Files'...")
        self.lbl_status.setStyleSheet("color: #475569; font-size: 12px;")
        self.lbl_tools = QLabel("")
        self.lbl_tools.setStyleSheet("color: #64748b; font-size: 11px;")

        status_bar.addWidget(self.lbl_status)
        status_bar.addStretch()
        status_bar.addWidget(self.lbl_tools)

        bottom_bar.addWidget(self.overall_progress)
        bottom_bar.addLayout(status_bar)
        root_layout.addLayout(bottom_bar)

    def _check_tools(self):
        """Displays status of the 4 required command line binaries."""
        tools = ["ffmpeg", "ffprobe", "SvtAv1EncApp", "exiftool"]
        paths = {t: resolve_tool_path(t) for t in tools}
        found_count = sum(1 for t in tools if os.path.exists(paths[t]) or shutil.which(paths[t]))
        self.lbl_tools.setText(f"Tools Detected: {found_count}/4 [FFmpeg, SVT-AV1, ExifTool]")

    def add_paths(self, paths: List[str]):
        """Accepts file paths and directories recursively."""
        new_files = []
        for p in paths:
            path_obj = Path(p)
            if path_obj.is_dir():
                for root, _, files in os.walk(path_obj):
                    for f in files:
                        fp = Path(root) / f
                        if fp.suffix.lower() in SUPPORTED_EXTS:
                            new_files.append(str(fp.resolve()))
            elif path_obj.is_file() and path_obj.suffix.lower() in SUPPORTED_EXTS:
                new_files.append(str(path_obj.resolve()))

        # Filter out duplicates
        existing_paths = {j["path"] for j in self.jobs}
        added_count = 0
        for f in new_files:
            if f not in existing_paths:
                self._add_job_row(f)
                added_count += 1

        if added_count > 0:
            self.lbl_status.setText(f"Added {added_count} new file(s). Total: {len(self.jobs)}")

    def _add_job_row(self, file_path: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        probe = MediaProbe.probe_file(file_path)
        is_photo = probe["is_photo"]
        if is_photo:
            if probe.get("has_gain_map"):
                media_type = "Photo (HDR GainMap)"
            else:
                media_type = "Photo"
            if probe.get("color_space_name") and probe["color_space_name"] != "sRGB":
                media_type += f" [{probe['color_space_name']}]"
        else:
            media_type = "Video"

        size_mb = probe["size_bytes"] / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB" if size_mb >= 1.0 else f"{probe['size_bytes'] / 1024:.0f} KB"
        res_str = f"{probe['width']}x{probe['height']}" if probe["width"] > 0 else "Unknown"
        if is_photo and probe["megapixels"] > 0:
            res_str += f" ({probe['megapixels']} MP)"

        # Item 0: File path / Name
        item_name = QTableWidgetItem(Path(file_path).name)
        item_name.setToolTip(file_path)
        self.table.setItem(row, 0, item_name)

        # Item 1: Media Type
        item_type = QTableWidgetItem(media_type)
        item_type.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 1, item_type)

        # Item 2: Resolution
        item_res = QTableWidgetItem(res_str)
        item_res.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, item_res)

        # Item 3: File Size
        item_size = QTableWidgetItem(size_str)
        item_size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, 3, item_size)

        # Item 4: Progress Bar
        pbar = QProgressBar()
        pbar.setRange(0, 100)
        pbar.setValue(0)
        pbar.setStyleSheet("QProgressBar { height: 14px; text-align: center; font-size: 10px; }")
        self.table.setCellWidget(row, 4, pbar)

        # Item 5: Status
        item_status = QTableWidgetItem("Queued")
        item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 5, item_status)

        job_info = {
            "path": file_path,
            "probe": probe,
            "row": row,
        }
        self.jobs.append(job_info)

    def _on_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Media Files", "",
            "Media Files (*.mp4 *.mkv *.mov *.avi *.webm *.jpg *.jpeg *.png *.webp *.bmp *.tiff);;All Files (*)"
        )
        if files:
            self.add_paths(files)

    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Media Folder")
        if folder:
            self.add_paths([folder])

    def _on_clear_jobs(self):
        if self.is_processing:
            QMessageBox.warning(self, "Batch Busy", "Please cancel the current batch before clearing jobs.")
            return
        self.jobs.clear()
        self.table.setRowCount(0)
        self.overall_progress.setValue(0)
        self.lbl_status.setText("Job list cleared.")

    def _on_open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.video_settings, self.photo_settings = dlg.get_settings()
            self.log_view.appendPlainText("[Settings] Applied updated video and photo settings.")

    def _on_batch_button_clicked(self):
        if self.is_processing:
            # Action: Cancel Batch
            if self.worker:
                self.btn_batch.setText("Cancelling...")
                self.btn_batch.setEnabled(False)
                self.lbl_status.setText("Cancelling batch processing...")
                self.worker.cancel()
        else:
            # Action: Start Batch
            if not self.jobs:
                QMessageBox.information(self, "No Jobs", "Please add files or folders to the job list first.")
                return

            self._start_batch()

    def _set_button_state_processing(self):
        self.is_processing = True
        self.btn_batch.setEnabled(True)
        self.btn_batch.setText("Cancel Batch")
        self.btn_batch.setStyleSheet(STYLE_PROCESSING)
        self.btn_settings.setEnabled(False)
        self.btn_add_files.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_clear.setEnabled(False)

    def _set_button_state_ready(self):
        self.is_processing = False
        self.btn_batch.setEnabled(True)
        self.btn_batch.setText("Start Batch")
        self.btn_batch.setStyleSheet(STYLE_READY)
        self.btn_settings.setEnabled(True)
        self.btn_add_files.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.btn_clear.setEnabled(True)

    def _start_batch(self):
        self._set_button_state_processing()
        self.overall_progress.setValue(0)
        self.lbl_status.setText(f"Batch running ({len(self.jobs)} items)...")

        # Reset rows status
        for row in range(self.table.rowCount()):
            pbar = self.table.cellWidget(row, 4)
            if pbar: pbar.setValue(0)
            self.table.setItem(row, 5, QTableWidgetItem("Queued"))

        self.worker = BatchWorker(self.jobs, self.video_settings, self.photo_settings)
        self.worker.job_started.connect(self._on_job_started)
        self.worker.job_progress.connect(self._on_job_progress)
        self.worker.job_finished.connect(self._on_job_finished)
        self.worker.batch_progress.connect(self.overall_progress.setValue)
        self.worker.batch_completed.connect(self._on_batch_completed)
        self.worker.log_message.connect(self.log_view.appendPlainText)

        self.worker.start()

    @pyqtSlot(int, str)
    def _on_job_started(self, idx: int, filename: str):
        if idx < self.table.rowCount():
            item_status = QTableWidgetItem("Processing")
            item_status.setForeground(QColor("#2563eb"))
            self.table.setItem(idx, 5, item_status)
        self.lbl_status.setText(f"Encoding [{idx + 1}/{len(self.jobs)}]: {filename}")

    @pyqtSlot(int, int, str)
    def _on_job_progress(self, idx: int, percent: int, msg: str):
        if idx < self.table.rowCount():
            pbar = self.table.cellWidget(idx, 4)
            if pbar:
                pbar.setValue(percent)
            item_status = QTableWidgetItem(msg)
            self.table.setItem(idx, 5, item_status)

    @pyqtSlot(int, bool, str)
    def _on_job_finished(self, idx: int, success: bool, msg: str):
        if idx < self.table.rowCount():
            pbar = self.table.cellWidget(idx, 4)
            if pbar:
                pbar.setValue(100)
            item_status = QTableWidgetItem("Completed" if success else "Failed")
            item_status.setForeground(QColor("#16a34a" if success else "#dc2626"))
            item_status.setToolTip(msg)
            self.table.setItem(idx, 5, item_status)

    @pyqtSlot(int, int, int)
    def _on_batch_completed(self, total: int, succeeded: int, failed: int):
        self._set_button_state_ready()
        self.lbl_status.setText(f"Batch completed: {succeeded}/{total} succeeded, {failed} failed.")
        QMessageBox.information(
            self,
            "Batch Complete",
            f"Batch encoding finished!\n\nTotal: {total}\nSucceeded: {succeeded}\nFailed: {failed}"
        )


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
