"""Incident detail viewer dialog."""

import os
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFormLayout, QGroupBox, QMessageBox, QScrollArea, QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from autolook.utils.host_names import resolve_display_name


def _best_image(inc: dict) -> str:
    """Prefer full screen copy, then thumbnail."""
    for key in ("screenshot_path", "thumbnail_path"):
        path = inc.get(key) or ""
        if path and Path(path).exists():
            return path
    return ""


class IncidentViewer(QDialog):
    def __init__(self, incident: dict, parent=None, host_aliases: dict | None = None):
        super().__init__(parent)
        self.incident = incident
        self.host_aliases = host_aliases or {}
        self.setWindowTitle(f"Incident #{incident.get('id', '?')}")
        self.setMinimumSize(900, 700)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        inc = self.incident

        image_path = _best_image(inc)
        if image_path:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setMinimumHeight(420)
                img_label = QLabel()
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                # Show large readable preview (up to ~1280 wide)
                scaled = pixmap.scaled(
                    1280, 720,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                img_label.setPixmap(scaled)
                img_label.setCursor(Qt.CursorShape.PointingHandCursor)
                img_label.mousePressEvent = lambda _e: self._open_screen()  # type: ignore[method-assign]
                container = QWidget()
                cl = QVBoxLayout(container)
                cl.addWidget(img_label)
                scroll.setWidget(container)
                layout.addWidget(scroll)
                hint = QLabel("Click image to open full screen file")
                hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hint.setStyleSheet("color: #666; font-size: 11px;")
                layout.addWidget(hint)
        else:
            missing = QLabel("No screen image for this alert")
            missing.setAlignment(Qt.AlignmentFlag.AlignCenter)
            missing.setStyleSheet("color: #888; padding: 24px;")
            layout.addWidget(missing)

        details = QGroupBox("Incident Details")
        form = QFormLayout(details)
        form.addRow("ID:", QLabel(str(inc.get("id", ""))))
        form.addRow("Time:", QLabel(str(inc.get("timestamp", ""))))
        form.addRow("End Time:", QLabel(str(inc.get("end_timestamp", "") or "")))
        form.addRow("Host:", QLabel(str(inc.get("host", ""))))
        mapped = resolve_display_name(inc.get("host", "") or "", self.host_aliases)
        form.addRow("Name:", QLabel(mapped or "(not mapped)"))
        form.addRow("User:", QLabel(str(inc.get("user", ""))))
        form.addRow("Source:", QLabel(str(inc.get("source", ""))))
        form.addRow("Detection:", QLabel(str(inc.get("detection_type", ""))))

        level = str(inc.get("alert_level", ""))
        from autolook.detection.alert_scorer import kind_label
        level_label = QLabel(kind_label(level))
        level_label.setStyleSheet(self._kind_style(level))
        form.addRow("Kind:", level_label)

        form.addRow("Confidence:", QLabel(f"{inc.get('confidence', 0) or 0:.2f}"))

        if inc.get("url"):
            form.addRow("URL:", QLabel(str(inc["url"])[:200]))
        if inc.get("app_name"):
            form.addRow("App:", QLabel(str(inc["app_name"])))
        if inc.get("video_source"):
            form.addRow("Video:", QLabel(str(inc["video_source"])))
            form.addRow("Video Time:", QLabel(f"{inc.get('video_timestamp_sec', 0) or 0:.1f}s"))
        if inc.get("screenshot_path"):
            form.addRow("Screen File:", QLabel(str(inc["screenshot_path"])))

        layout.addWidget(details)

        if inc.get("description"):
            desc_box = QGroupBox("Description")
            dl = QVBoxLayout(desc_box)
            dl.addWidget(QLabel(str(inc["description"])))
            layout.addWidget(desc_box)

        if inc.get("raw_text"):
            raw_box = QGroupBox("Raw Text")
            rl = QVBoxLayout(raw_box)
            raw_label = QLabel(str(inc["raw_text"])[:500])
            raw_label.setWordWrap(True)
            rl.addWidget(raw_label)
            layout.addWidget(raw_box)

        media_box = QGroupBox("Open Media")
        ml = QHBoxLayout(media_box)
        btn_screen = QPushButton("Open Screen Image")
        btn_screen.clicked.connect(self._open_screen)
        ml.addWidget(btn_screen)
        btn_thumb = QPushButton("Open Thumbnail")
        btn_thumb.clicked.connect(self._open_thumbnail)
        ml.addWidget(btn_thumb)
        btn_source = QPushButton("Open Source File")
        btn_source.clicked.connect(self._open_source)
        ml.addWidget(btn_source)
        btn_folder = QPushButton("Open Folder")
        btn_folder.clicked.connect(self._open_folder)
        ml.addWidget(btn_folder)
        layout.addWidget(media_box)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _open_path(self, path: str):
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "Open", f"File not found:\n{path}")
            return
        try:
            os.startfile(path)  # noqa: S606 — Windows open with default app
        except Exception as e:
            QMessageBox.warning(self, "Open", str(e))

    def _open_screen(self):
        path = _best_image(self.incident)
        self._open_path(path)

    def _open_thumbnail(self):
        self._open_path(self.incident.get("thumbnail_path") or "")

    def _open_source(self):
        video = self.incident.get("video_source") or ""
        path = video if video and Path(video).exists() else _best_image(self.incident)
        self._open_path(path)

    def _open_folder(self):
        video = self.incident.get("video_source") or ""
        path = video if video and Path(video).exists() else _best_image(self.incident)
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "Open", "No media file to locate.")
            return
        folder = str(Path(path).parent)
        try:
            subprocess.Popen(["explorer", "/select,", str(Path(path))])
        except Exception:
            os.startfile(folder)

    def _kind_style(self, kind: str) -> str:
        kind = (kind or "").lower()
        if kind == "nsfw+korea" or "nsfw" in kind and "korea" in kind:
            return "background-color: #8e24aa; color: white; padding: 2px 8px;"
        if kind == "nsfw" or "nsfw" in kind:
            return "background-color: #d32f2f; color: white; padding: 2px 8px;"
        if kind == "korea" or "korea" in kind or "hangul" in kind:
            return "background-color: #1565c0; color: white; padding: 2px 8px;"
        return "background-color: #757575; color: white; padding: 2px 8px;"
