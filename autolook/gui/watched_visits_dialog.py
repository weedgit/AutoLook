"""Watched web/app visit history dialog."""

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QAbstractItemView, QComboBox, QPushButton,
    QDateTimeEdit, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QDate, QDateTime, QTime

from autolook.config import Config
from autolook.db.visit_store import VisitStore
from autolook.utils.host_names import resolve_display_name
from autolook.utils.screen_match import parse_event_time


class WatchedVisitsDialog(QDialog):
    """Show From / To / Name / Source for watched website & app visits."""

    def __init__(self, store: VisitStore, config: Config, parent=None):
        super().__init__(parent)
        self.store = store
        self.config = config
        self._rows: list[dict] = []
        self.setWindowTitle("Watched web / app")
        self.setMinimumSize(820, 480)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

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

        filt.addWidget(QLabel("From:"))
        self._from = QDateTimeEdit()
        self._from.setCalendarPopup(True)
        self._from.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._from.setDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0)))
        self._from.dateTimeChanged.connect(lambda _: self.refresh())
        filt.addWidget(self._from)

        filt.addWidget(QLabel("To:"))
        self._to = QDateTimeEdit()
        self._to.setCalendarPopup(True)
        self._to.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._to.setDateTime(QDateTime(QDate(2099, 12, 31), QTime(23, 59)))
        self._to.dateTimeChanged.connect(lambda _: self.refresh())
        filt.addWidget(self._to)

        btn_all = QPushButton("All time")
        btn_all.clicked.connect(self._reset_time)
        filt.addWidget(btn_all)

        filt.addStretch()
        self._count = QLabel("")
        filt.addWidget(self._count)
        layout.addLayout(filt)

        hint = QLabel(
            "Visit history for Watched Websites / Watched Apps (Settings → Watchlists). "
            "Continuous use merges into one row; To updates while they stay on it.\n"
            f"Saved in SQLite: {config.visits_db_path}"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        layout.addWidget(hint)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["From", "To", "Name", "Source"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        btns = QHBoxLayout()
        save_csv = QPushButton("Save CSV")
        save_csv.clicked.connect(self._export_csv)
        btns.addWidget(save_csv)
        btns.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        layout.addLayout(btns)

    def _reset_time(self):
        self._from.blockSignals(True)
        self._to.blockSignals(True)
        self._from.setDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0)))
        self._to.setDateTime(QDateTime(QDate(2099, 12, 31), QTime(23, 59)))
        self._from.blockSignals(False)
        self._to.blockSignals(False)
        self.refresh()

    def refresh(self):
        visits = self.store.get_visits()
        aliases = self.config.host_aliases
        from_ts = self._from.dateTime().toSecsSinceEpoch()
        to_ts = self._to.dateTime().toSecsSinceEpoch()
        name_f = self._name.currentText()
        src_f = self._source.currentText()

        names = sorted({
            resolve_display_name(v.get("host", "") or "", aliases) or (v.get("host") or "—")
            for v in visits
        })
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
            ts = parse_event_time(v.get("timestamp") or "")
            if ts is not None and (ts < from_ts or ts > to_ts):
                continue
            display = resolve_display_name(v.get("host", "") or "", aliases) or (v.get("host") or "—")
            if name_f != "All" and display != name_f:
                continue
            if src_f != "All" and (v.get("source") or "") != src_f:
                continue
            rows.append({**v, "name": display})

        self._rows = rows
        self._count.setText(f"{len(rows)} visit(s)")
        self._table.setRowCount(len(rows))
        for i, v in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(str(v.get("timestamp") or "")))
            self._table.setItem(i, 1, QTableWidgetItem(str(v.get("end_timestamp") or "")))
            self._table.setItem(i, 2, QTableWidgetItem(str(v.get("name") or "")))
            self._table.setItem(i, 3, QTableWidgetItem(str(v.get("source") or "")))

    def _export_csv(self):
        if not self._rows:
            QMessageBox.information(self, "Save", "No visits to save.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save watched visits", "autolook_watched_visits.csv", "CSV (*.csv)"
        )
        if not path:
            return
        import csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["From", "To", "Name", "Source", "Host", "Kind", "URL", "App"])
            w.writeheader()
            for v in self._rows:
                w.writerow({
                    "From": v.get("timestamp", ""),
                    "To": v.get("end_timestamp", ""),
                    "Name": v.get("name", ""),
                    "Source": v.get("source", ""),
                    "Host": v.get("host", ""),
                    "Kind": v.get("kind", ""),
                    "URL": v.get("url", ""),
                    "App": v.get("app_name", ""),
                })
        QMessageBox.information(self, "Save", f"Saved {len(self._rows)} visit(s) to:\n{path}")
