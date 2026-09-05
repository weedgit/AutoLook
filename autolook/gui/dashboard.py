"""Alert dashboard — NSFW / Korea alerts (SQLite-backed)."""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QComboBox, QLabel, QHeaderView, QAbstractItemView, QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPixmap, QIcon

from autolook.config import Config
from autolook.db.incident_db import AlertStore
from autolook.detection.alert_scorer import (
    incident_has_korea,
    incident_has_nsfw,
    kind_label,
)
from autolook.utils.host_names import resolve_display_name

KIND_COLORS = {
    "nsfw": QColor(220, 50, 50),
    "korea": QColor(30, 100, 200),
    "nsfw+korea": QColor(140, 40, 160),
}

THUMB_SIZE = QSize(160, 90)


class DashboardWidget(QWidget):
    incident_selected = pyqtSignal(dict)

    def __init__(self, store: AlertStore, config: Config, parent=None):
        super().__init__(parent)
        self.store = store
        self.config = config
        self._incidents: list[dict] = []
        self._period_start: str | None = None
        self._period_end: str | None = None
        self._build_ui()
        self.refresh()

    def set_period_filter(self, start: str | None = None, end: str | None = None):
        """Limit rows to alerts overlapping [start, end]. None = no bound."""
        self._period_start = start
        self._period_end = end
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("NSFW / Korea alerts")
        title.setStyleSheet("font-weight: bold; padding: 2px 0;")
        layout.addWidget(title)

        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Show:"))
        self._chk_nsfw = QCheckBox("NSFW")
        self._chk_nsfw.setChecked(True)
        self._chk_nsfw.setToolTip("Show NSFW alerts")
        self._chk_nsfw.toggled.connect(lambda _: self.refresh())
        filter_layout.addWidget(self._chk_nsfw)

        self._chk_korea = QCheckBox("Korea")
        self._chk_korea.setChecked(True)
        self._chk_korea.setToolTip("Show Korea alerts")
        self._chk_korea.toggled.connect(lambda _: self.refresh())
        filter_layout.addWidget(self._chk_korea)

        filter_layout.addWidget(QLabel("Name:"))
        self._name_combo = QComboBox()
        self._name_combo.addItem("All")
        self._name_combo.currentTextChanged.connect(lambda _: self.refresh())
        filter_layout.addWidget(self._name_combo)

        self._with_image = QCheckBox("Has screen")
        self._with_image.setChecked(False)
        self._with_image.setToolTip(
            "When checked, hide alerts that have no screen picture "
            "(for example web-log hits with no recording image)."
        )
        self._with_image.stateChanged.connect(lambda _: self.refresh())
        filter_layout.addWidget(self._with_image)

        filter_layout.addStretch()
        self._count = QLabel("")
        self._count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        filter_layout.addWidget(self._count)
        layout.addLayout(filter_layout)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Thumb", "Kind", "From", "To", "Name", "Source",
            "Detection", "Description",
        ])
        self._table.setIconSize(THUMB_SIZE)
        self._table.verticalHeader().setDefaultSectionSize(100)
        self._table.setColumnWidth(0, 170)
        self._table.setColumnWidth(2, 140)
        self._table.setColumnWidth(3, 140)
        self._table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

    def refresh(self):
        name_filter = self._name_combo.currentText()
        incidents = self.store.get_incidents(
            limit=50000,
            start=self._period_start,
            end=self._period_end,
        )

        filtered = []
        for inc in incidents:
            keep = False
            if self._chk_nsfw.isChecked() and incident_has_nsfw(inc):
                keep = True
            if self._chk_korea.isChecked() and incident_has_korea(inc):
                keep = True
            if not keep:
                continue

            if self._with_image.isChecked():
                has_file = False
                for key in ("screenshot_path", "thumbnail_path"):
                    p = inc.get(key) or ""
                    if p and Path(p).exists():
                        has_file = True
                        break
                if not has_file:
                    continue
            filtered.append(inc)

        aliases = self.config.host_aliases
        if name_filter and name_filter != "All":
            filtered = [
                inc for inc in filtered
                if resolve_display_name(inc.get("host", ""), aliases) == name_filter
            ]
        self._incidents = filtered
        self._count.setText(f"{len(filtered)} alert(s)")
        self._refresh_name_filter(aliases)
        self._populate_table()

    def _refresh_name_filter(self, aliases: dict[str, str]):
        current = self._name_combo.currentText()
        names = sorted({v for v in aliases.values() if v})
        self._name_combo.blockSignals(True)
        self._name_combo.clear()
        self._name_combo.addItem("All")
        self._name_combo.addItems(names)
        idx = self._name_combo.findText(current)
        self._name_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._name_combo.blockSignals(False)

    def _populate_table(self):
        aliases = self.config.host_aliases
        self._table.setRowCount(len(self._incidents))
        for i, inc in enumerate(self._incidents):
            kind = inc.get("alert_level", "") or ""
            label = kind_label(kind)
            host = inc.get("host", "") or ""
            display_name = resolve_display_name(host, aliases) or "—"

            thumb_item = QTableWidgetItem()
            thumb_path = ""
            for key in ("screenshot_path", "thumbnail_path"):
                p = inc.get(key) or ""
                if p and Path(p).exists():
                    thumb_path = p
                    break
            if thumb_path:
                pix = QPixmap(thumb_path)
                if not pix.isNull():
                    thumb_item.setIcon(QIcon(pix.scaled(
                        THUMB_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )))
            self._table.setItem(i, 0, thumb_item)

            end = inc.get("end_timestamp") or ""
            start = inc.get("timestamp", "") or ""
            if end in (None, ""):
                end = start
            # Legacy video-second markers
            end_s = str(end)
            if end_s.replace(".", "", 1).isdigit() and float(end_s) < 1e9:
                end_s = f"{start} (+{end_s}s)" if start else f"+{end_s}s"

            items = [
                label,
                start,
                end_s,
                display_name,
                inc.get("source", ""),
                inc.get("detection_type", ""),
                (inc.get("description", "") or "")[:100],
            ]
            for j, text in enumerate(items):
                item = QTableWidgetItem(str(text))
                if j == 0:
                    color_key = kind if kind in KIND_COLORS else None
                    if not color_key:
                        if incident_has_nsfw(inc) and incident_has_korea(inc):
                            color_key = "nsfw+korea"
                        elif incident_has_nsfw(inc):
                            color_key = "nsfw"
                        elif incident_has_korea(inc):
                            color_key = "korea"
                    if color_key and color_key in KIND_COLORS:
                        item.setBackground(KIND_COLORS[color_key])
                        item.setForeground(QColor(255, 255, 255))
                self._table.setItem(i, j + 1, item)

    def _on_double_click(self, index):
        row = index.row()
        if 0 <= row < len(self._incidents):
            self.incident_selected.emit(self._incidents[row])
