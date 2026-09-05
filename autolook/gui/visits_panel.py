"""Watched web/app visit panel for the main window."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QAbstractItemView, QComboBox,
)
from PyQt6.QtCore import Qt

from autolook.config import Config
from autolook.db.visit_store import VisitStore
from autolook.utils.host_names import resolve_display_name
from autolook.utils.time_range import format_from_to


class VisitsPanel(QWidget):
    """Time / Name / Source for watched website & app visits (SQLite)."""

    def __init__(self, store: VisitStore, config: Config, parent=None):
        super().__init__(parent)
        self.store = store
        self.config = config
        self._rows: list[dict] = []
        self._period_start: str | None = None
        self._period_end: str | None = None
        self._build_ui()
        self.refresh()

    def set_period_filter(self, start: str | None = None, end: str | None = None):
        """Limit rows to visits overlapping [start, end]. None = no bound."""
        self._period_start = start
        self._period_end = end
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Watched web / app")
        title.setStyleSheet("font-weight: bold; padding: 2px 0;")
        layout.addWidget(title)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Name:"))
        self._name = QComboBox()
        self._name.addItem("All")
        self._name.currentTextChanged.connect(lambda _: self.refresh())
        filt.addWidget(self._name)

        filt.addWidget(QLabel("Source:"))
        self._source = QComboBox()
        self._source.addItem("All")
        self._source.currentTextChanged.connect(lambda _: self.refresh())
        filt.addWidget(self._source)

        filt.addStretch()
        self._count = QLabel("")
        filt.addWidget(self._count)
        layout.addLayout(filt)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Time", "Name", "Source"])
        self._table.setColumnWidth(0, 240)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

    def refresh(self):
        visits = self.store.get_visits(
            start=self._period_start,
            end=self._period_end,
        )
        aliases = self.config.host_aliases

        # Same Name filter list as NSFW/Korea alerts (host aliases only)
        names = sorted({v for v in aliases.values() if v})
        sources = sorted({v.get("source") or "" for v in visits if v.get("source")})

        self._name.blockSignals(True)
        cur_n = self._name.currentText()
        self._name.clear()
        self._name.addItem("All")
        self._name.addItems(names)
        idx = self._name.findText(cur_n)
        self._name.setCurrentIndex(idx if idx >= 0 else 0)
        self._name.blockSignals(False)

        self._source.blockSignals(True)
        cur_s = self._source.currentText()
        self._source.clear()
        self._source.addItem("All")
        self._source.addItems(sources)
        idx = self._source.findText(cur_s)
        self._source.setCurrentIndex(idx if idx >= 0 else 0)
        self._source.blockSignals(False)
        name_f = self._name.currentText()
        src_f = self._source.currentText()

        rows = []
        for v in visits:
            # Same as alerts table: alias name, else "—"
            display = resolve_display_name(v.get("host", "") or "", aliases) or "—"
            if name_f != "All" and display != name_f:
                continue
            if src_f != "All" and (v.get("source") or "") != src_f:
                continue
            rows.append({**v, "name": display})

        self._rows = rows
        self._count.setText(f"{len(rows)} visit(s)")
        self._table.setRowCount(len(rows))
        for i, v in enumerate(rows):
            time_txt = format_from_to(v.get("timestamp"), v.get("end_timestamp"))
            self._table.setItem(i, 0, QTableWidgetItem(time_txt))
            self._table.setItem(i, 1, QTableWidgetItem(str(v.get("name") or "—")))
            self._table.setItem(i, 2, QTableWidgetItem(str(v.get("source") or "")))
