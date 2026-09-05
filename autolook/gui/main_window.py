"""Main application window for AutoLook."""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QToolBar, QStatusBar, QSplitter,
    QMessageBox, QSystemTrayIcon, QMenu, QFileDialog, QLabel, QWidget,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor

from autolook.config import Config
from autolook.db.netmonitor_db import NetMonitorDB
from autolook.db.incident_db import AlertStore
from autolook.db.memory_alert_store import MemoryAlertStore
from autolook.db.visit_store import VisitStore
from autolook.engine.history_folder import inspect_history_folder
from autolook.engine.scanner import Scanner
from autolook.engine.worker import ScanWorker, HistoryScanWorker
from autolook.gui.dashboard import DashboardWidget
from autolook.gui.visits_panel import VisitsPanel
from autolook.gui.settings_dialog import SettingsDialog
from autolook.gui.incident_viewer import IncidentViewer
from autolook.gui.period_dialog import PeriodDialog
from autolook.gui.status_log import StatusLogPanel
from autolook.utils.log_handler import install_gui_logging
from autolook.utils.alert_sound import play_alert_sound

logger = logging.getLogger(__name__)

LOG_PANEL_DEFAULT_WIDTH = 280


def _make_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setBrush(QColor(30, 136, 229))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawEllipse(10, 10, 12, 12)
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoLook — Content Detection for Net Monitor")
        self.setMinimumSize(1100, 700)

        self.config = Config()
        self.nm_db = NetMonitorDB(self.config.netmonitor_db_path)
        self.store = AlertStore(self.config.autolook_db_path)
        self.visits = VisitStore(self.config.visits_db_path)
        self.scanner = Scanner(self.config, self.nm_db, self.store, self.visits)
        self._history_alert_store: MemoryAlertStore | None = None

        self._mode = "runtime"
        self._watching = False
        self._history_ready = False
        self._scan_worker: ScanWorker | None = None
        self._history_worker: HistoryScanWorker | None = None
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._on_runtime_tick)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)

        self._build_ui()
        self._build_tray()
        install_gui_logging(self._log_panel)
        self._log("AutoLook started — runtime mode", "SUCCESS")
        self._log(f"Net Monitor DB: {self.config.netmonitor_db_path}")
        self._log(f"Alerts DB: {self.config.autolook_db_path}")
        self._log(f"Watched visits DB: {self.config.visits_db_path}")
        rec = self.config.recording_path
        if rec and rec.exists():
            self._log(f"Recording path: {rec}", "SUCCESS")
        else:
            self._log("Recording path not set — video/screenshot scan disabled", "WARN")
        self._clock_timer.start(1000)
        self._tick_clock()
        self._start_runtime_watch()

    def _log(self, message: str, level: str = "INFO"):
        self._log_panel.log(message, level)

    def _build_ui(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._mode_label = QLabel("Runtime")
        self._mode_label.setStyleSheet("padding: 0 8px; color: #1565c0; font-weight: bold;")
        toolbar.addWidget(self._mode_label)

        toolbar.addSeparator()

        self._act_watch = QAction("Stop Watching", self)
        self._act_watch.setCheckable(True)
        self._act_watch.setChecked(True)
        self._act_watch.triggered.connect(self._on_toggle_watch)
        toolbar.addAction(self._act_watch)

        self._act_history = QAction("Scan History", self)
        self._act_history.triggered.connect(self._on_scan_history)
        toolbar.addAction(self._act_history)

        self._act_stop_history = QAction("Stop History", self)
        self._act_stop_history.setEnabled(False)
        self._act_stop_history.setToolTip("Stop the current history scan (keeps alerts found so far)")
        self._act_stop_history.triggered.connect(self._on_stop_history)
        toolbar.addAction(self._act_stop_history)

        self._act_saved = QAction("Saved History", self)
        self._act_saved.setToolTip(
            "Stop watching and show Alerts + Watched web/app from the database for a period"
        )
        self._act_saved.triggered.connect(self._on_saved_history)
        toolbar.addAction(self._act_saved)

        toolbar.addSeparator()

        self._act_toggle_log = QAction("Status Log", self)
        self._act_toggle_log.setCheckable(True)
        self._act_toggle_log.setChecked(True)
        self._act_toggle_log.triggered.connect(self._on_toggle_log_panel)
        toolbar.addAction(self._act_toggle_log)

        self._act_settings = QAction("Settings", self)
        self._act_settings.triggered.connect(self._on_settings)
        toolbar.addAction(self._act_settings)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self._clock = QLabel()
        self._clock.setMinimumWidth(160)
        self._clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._clock.setStyleSheet("font-weight: bold; padding: 0 12px;")
        toolbar.addWidget(self._clock)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        tables = QSplitter(Qt.Orientation.Vertical)
        self.dashboard = DashboardWidget(self.store, self.config)
        self.dashboard.incident_selected.connect(self._on_incident_selected)
        tables.addWidget(self.dashboard)

        self.visits_panel = VisitsPanel(self.visits, self.config)
        tables.addWidget(self.visits_panel)
        tables.setStretchFactor(0, 3)
        tables.setStretchFactor(1, 2)
        tables.setSizes([480, 280])
        self._splitter.addWidget(tables)

        self._log_panel = StatusLogPanel()
        self._log_panel.clear_requested.connect(self._on_clear)
        self._splitter.addWidget(self._log_panel)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setSizes([800, LOG_PANEL_DEFAULT_WIDTH])
        self.setCentralWidget(self._splitter)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

    def _active_alert_store(self):
        """SQLite for runtime; memory-only store while viewing history results."""
        if self._mode == "history" and self._history_alert_store is not None:
            return self._history_alert_store
        return self.store

    def _use_runtime_alert_store(self):
        self.scanner.inc_db = self.store
        self.dashboard.store = self.store
        self.dashboard.refresh()

    def _use_history_alert_store(self):
        if self._history_alert_store is None:
            self._history_alert_store = MemoryAlertStore()
        self.scanner.inc_db = self._history_alert_store
        self.dashboard.store = self._history_alert_store
        self.dashboard.refresh()

    def _tick_clock(self):
        try:
            self._clock.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        except RuntimeError:
            pass

    def _set_mode(self, mode: str):
        self._mode = mode
        if mode == "history":
            label, color = "History", "#6a1b9a"
        elif mode == "saved":
            label, color = "Saved", "#2e7d32"
        else:
            label, color = "Runtime", "#1565c0"
        self._mode_label.setText(label)
        self._mode_label.setStyleSheet(f"padding: 0 8px; color: {color}; font-weight: bold;")

    def _on_toggle_log_panel(self, visible: bool):
        self._log_panel.setVisible(visible)

    def _build_tray(self):
        self._tray_icon = QSystemTrayIcon(_make_icon(), self)
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.show)
        show_action.triggered.connect(self.raise_)
        toggle_watch = tray_menu.addAction("Toggle Watching")
        toggle_watch.triggered.connect(lambda: self._act_watch.trigger())
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self._quit_app)
        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _quit_app(self):
        self._watching = False
        self._shutdown_workers()
        try:
            self.store.close()
        except Exception:
            pass
        try:
            self.visits.close()
        except Exception:
            pass
        QApplication.quit()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()

    def closeEvent(self, event):
        if self._watching and self._mode == "runtime":
            event.ignore()
            self.hide()
            self._log("Minimized to tray (runtime watch continues)", "WARN")
            self._tray_icon.showMessage(
                "AutoLook", "Still watching. Right-click tray to quit.",
                QSystemTrayIcon.MessageIcon.Information, 3000,
            )
        else:
            self._shutdown_workers()
            event.accept()

    def _wait_for_workers(self, timeout_ms: int = 120_000) -> None:
        """Block until scan/history threads finish (or timeout/terminate)."""
        if self._history_worker is not None:
            try:
                self._history_worker.stop()
            except Exception:
                pass
        for attr in ("_scan_worker", "_history_worker"):
            worker = getattr(self, attr, None)
            if worker is None:
                continue
            try:
                if worker.isRunning():
                    if not worker.wait(timeout_ms):
                        logger.warning("%s still running after wait — terminating", attr)
                        worker.terminate()
                        worker.wait(3000)
            except RuntimeError:
                pass
            setattr(self, attr, None)

    def _set_history_busy(self, busy: bool) -> None:
        self._act_history.setEnabled(not busy)
        self._act_stop_history.setEnabled(busy)
        self._act_watch.setEnabled(not busy)

    def _shutdown_workers(self):
        """Stop timers and wait for scan threads before dropping references.

        ScanWorker/HistoryScanWorker are one-shot run() threads — QThread.quit()
        does nothing for them. Dropping the Python ref while still running causes
        the console error: QThread: Destroyed while thread is still running.
        """
        self._watching = False
        self._watch_timer.stop()
        self._clock_timer.stop()
        self._wait_for_workers()

    @staticmethod
    def _worker_running(worker) -> bool:
        if worker is None:
            return False
        try:
            return bool(worker.isRunning())
        except RuntimeError:
            return False

    def _update_status(self):
        total = self._active_alert_store().incident_count()
        visits = self.visits.count()
        watching = "WATCHING" if self._watching else "IDLE"
        self._statusbar.showMessage(
            f"{self._mode.upper()} | {watching} | Alerts: {total} | "
            f"Watched visits: {visits} | Interval: {self.config.scan_interval}s"
        )

    def _start_runtime_watch(self):
        self._set_mode("runtime")
        self._use_runtime_alert_store()
        self._history_ready = False
        self.scanner.begin_runtime()
        # Runtime: show only visits/alerts from this watch start; DB keeps older rows
        since = getattr(self.scanner, "_visits_session_start", None)
        self.dashboard.set_period_filter(start=since, end=None)
        self.visits_panel.set_period_filter(start=since, end=None)
        self._watching = True
        self._act_watch.blockSignals(True)
        self._act_watch.setChecked(True)
        self._act_watch.setText("Stop Watching")
        self._act_watch.blockSignals(False)
        self._watch_timer.start(self.config.scan_interval * 1000)
        self._log(
            f"Runtime watch started (every {self.config.scan_interval}s) — "
            "tables show data from this start; Saved History browses full DB",
            "SUCCESS",
        )
        self._update_status()
        self._on_runtime_tick()

    def _stop_watch(self):
        self._watching = False
        self._watch_timer.stop()
        self._act_watch.blockSignals(True)
        self._act_watch.setChecked(False)
        self._act_watch.setText("Start Watching")
        self._act_watch.blockSignals(False)
        self._update_status()

    def _on_toggle_watch(self, checked: bool):
        if self._mode == "history":
            self._act_watch.blockSignals(True)
            self._act_watch.setChecked(False)
            self._act_watch.blockSignals(False)
            self._log("Use Scan History to pick a folder, then Watch in the period dialog", "WARN")
            return
        if checked:
            self._start_runtime_watch()
        else:
            self._stop_watch()
            self._log("Runtime watch stopped")

    def _on_saved_history(self):
        """Stop watching and browse Alerts + Watched visits from SQLite by period."""
        if self._worker_running(self._history_worker):
            self._log("Stop the folder history scan first", "WARN")
            return
        self._stop_watch()
        self._act_watch.blockSignals(True)
        self._act_watch.setChecked(False)
        self._act_watch.setText("Start Watching")
        self._act_watch.blockSignals(False)

        end = datetime.now()
        start = end - timedelta(days=7)

        dlg = PeriodDialog(
            start,
            end,
            self,
            title="Saved history period",
            hint=(
                "Show Alerts and Watched web/app already saved in the database.\n"
                "Set From / To, then Show. Watching is stopped while you browse."
            ),
            ok_text="Show",
        )
        if not dlg.exec():
            self._log("Saved history cancelled")
            self._start_runtime_watch()
            return

        period_start, period_end = dlg.period()
        self._set_mode("saved")
        self._use_runtime_alert_store()  # SQLite alerts (not memory scan store)
        self.dashboard.set_period_filter(start=period_start, end=period_end)
        self.visits_panel.set_period_filter(start=period_start, end=period_end)
        n_alerts = self.dashboard._table.rowCount()
        n_visits = self.visits_panel._table.rowCount()
        self._log(
            f"Saved history {period_start} → {period_end}: "
            f"{n_alerts} alert(s), {n_visits} visit(s)",
            "SUCCESS",
        )
        self._statusbar.showMessage(
            f"Saved history {period_start} → {period_end}",
            8000,
        )
        self._update_status()

    def _on_clear(self):
        """Clear table views + status log only. Does not delete SQLite rows.

        After clear, only new alerts/visits from this moment appear in the tables.
        Use Saved History to browse older DB rows again.
        """
        since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.dashboard.set_period_filter(start=since, end=None)
        self.visits_panel.set_period_filter(start=since, end=None)
        # Keep runtime session marker in sync with the cleared view
        if hasattr(self.scanner, "_visits_session_start"):
            self.scanner._visits_session_start = since
        self._log_panel.clear()
        self._history_ready = False
        self._update_status()
        self._log(
            f"Tables and status log cleared (DB kept). "
            f"New alerts / watched visits will show from {since}",
            "WARN",
        )

    def _on_scan_history(self):
        self._stop_watch()
        start_dir = str(self.config.recording_path or "")
        folder = QFileDialog.getExistingDirectory(self, "Select history folder", start_dir)
        if not folder:
            self._log("History cancelled")
            self._start_runtime_watch()
            return
        info = inspect_history_folder(Path(folder))
        if not info["has_data"]:
            QMessageBox.warning(
                self,
                "No history data",
                "No video, screen image, or CSV files in this folder.",
            )
            self._log("History folder has no recorded data", "WARN")
            self._start_runtime_watch()
            return

        self._set_mode("history")
        self._log(
            f"History folder: {folder} "
            f"({info['video_count']} video, {info['image_count']} image, "
            f"{len(info['csvs'])} csv)",
            "SUCCESS",
        )
        dlg = PeriodDialog(
            info["start"],
            info["end"],
            self,
        )
        if not dlg.exec():
            self._log("History period cancelled")
            self._start_runtime_watch()
            return
        start, end = dlg.period()
        self._run_history_watch(folder, start, end)

    def _run_history_watch(
        self,
        folder: str,
        start: str,
        end: str,
    ):
        if self._worker_running(self._history_worker):
            self._log("History watch already running", "WARN")
            return
        # History folder scan results stay in memory only — never written to SQLite
        self._history_alert_store = MemoryAlertStore()
        self._use_history_alert_store()
        self.dashboard.set_period_filter(None, None)
        self.visits_panel.set_period_filter(None, None)
        self._set_history_busy(True)
        video_note = "images + video" if self.config.include_video else "images only"
        self._log(
            f"History watch ({video_note}): {start} → {end} "
            "(results not saved to DB)",
            "WARN",
        )
        self._statusbar.showMessage(f"History watching {start} to {end}...")
        self._history_worker = HistoryScanWorker(
            self.scanner,
            folder,
            start,
            end,
            self,
        )
        self._history_worker.progress.connect(lambda m: self._log(m))
        self._history_worker.finished.connect(self._on_history_finished)
        self._history_worker.error.connect(self._on_history_error)
        self._history_worker.start()

    def _on_stop_history(self):
        if not self._worker_running(self._history_worker):
            self._set_history_busy(False)
            return
        self._log("Stopping history scan…", "WARN")
        self._statusbar.showMessage("Stopping history scan…")
        self._act_stop_history.setEnabled(False)
        try:
            self._history_worker.stop()
        except Exception:
            pass

    def _on_history_finished(self, incidents: list):
        stopped = bool(
            self._history_worker is not None
            and getattr(self._history_worker, "was_stopped", False)
        )
        self._set_history_busy(False)
        self._history_worker = None
        self.dashboard.refresh()
        self.visits_panel.refresh()
        self._history_ready = True
        msg = (
            f"History stopped: {len(incidents)} alert(s)"
            if stopped
            else f"History done: {len(incidents)} alert(s)"
        )
        self._log(msg, "SUCCESS" if incidents else "INFO")
        for inc in incidents[:5]:
            kind = (inc.get("alert_level") or "?").upper()
            desc = (inc.get("description") or "")[:60]
            self._log(f"  [{kind}] {desc}")
        if len(incidents) > 5:
            self._log(f"  ... and {len(incidents) - 5} more")
        self._statusbar.showMessage(msg, 8000)
        self._update_status()
        if incidents:
            self._maybe_play_alert()

    def _on_history_error(self, error: str):
        self._history_worker = None
        self._set_history_busy(False)
        self._log(f"History error: {error}", "ERROR")
        QMessageBox.warning(self, "History", error)
        self._update_status()

    def _on_runtime_tick(self):
        if self._mode != "runtime" or not self._watching:
            return
        if self._worker_running(self._scan_worker):
            return
        self._scan_worker = ScanWorker(self.scanner, self)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    def _on_scan_finished(self, incidents: list):
        self._scan_worker = None
        now = datetime.now().strftime("%H:%M:%S")
        if incidents:
            self.dashboard.refresh()
            self.visits_panel.refresh()
            self._update_status()
            new_ones = [i for i in incidents if not i.get("merged")]
            extended = [i for i in incidents if i.get("merged")]
            if new_ones and extended:
                msg = f"{len(new_ones)} new alert(s), {len(extended)} session(s) extended"
            elif new_ones:
                msg = f"{len(new_ones)} new alert(s)"
            else:
                msg = f"{len(extended)} alert session(s) updated (To extended)"
            self._log(msg, "WARN" if new_ones else "INFO")
            for inc in incidents[:8]:
                kind = (inc.get("alert_level") or "?").upper()
                tag = "extend" if inc.get("merged") else "new"
                host = inc.get("host") or ""
                detail = (
                    inc.get("url")
                    or inc.get("title")
                    or inc.get("app_name")
                    or inc.get("caption")
                    or inc.get("file_name")
                    or ""
                )
                if not detail:
                    src = inc.get("screenshot_path") or inc.get("video_source") or ""
                    detail = Path(src).name if src else (inc.get("source") or "")
                desc = (inc.get("description") or "")[:50]
                self._log(
                    f"  [{kind}/{tag}] {host} | {detail} | {desc}".strip(" |")
                )
            self._statusbar.showMessage(
                f"Last check {now} | {msg} | "
                f"Interval: {self.config.scan_interval}s",
                8000,
            )
            if new_ones:
                self._maybe_play_alert()
                if not self.isVisible():
                    self._tray_icon.showMessage(
                        "AutoLook Alert", msg,
                        QSystemTrayIcon.MessageIcon.Warning, 5000,
                    )
        else:
            # Visits may have changed without NSFW/Korea alerts
            self.visits_panel.refresh()
            self._update_status()
            self._statusbar.showMessage(
                f"Last check {now} | Watching OK — no new alerts | "
                f"Interval: {self.config.scan_interval}s"
            )

    def _maybe_play_alert(self):
        if self.config.alert_sound:
            play_alert_sound()

    def _on_scan_error(self, error: str):
        self._scan_worker = None
        self._log(f"Scan error: {error}", "ERROR")

    def _on_settings(self):
        dlg = SettingsDialog(self.config, self, nm_db=self.nm_db)
        if dlg.exec():
            was_watching = self._watching and self._mode == "runtime"
            if self._worker_running(self._scan_worker) or self._worker_running(self._history_worker):
                self._log("Waiting for current scan to finish before applying settings...", "WARN")
                self._watch_timer.stop()
                self._wait_for_workers()
            self.config.save()
            self.scanner = Scanner(self.config, self.nm_db, self.store, self.visits)
            if self._mode == "history" and self._history_alert_store is not None:
                self.scanner.inc_db = self._history_alert_store
            self._log(
                f"Settings saved - NSFW={'on' if self.config.alert_nsfw else 'off'} "
                f"({self.config.nsfw_engine}, {self.config.nsfw_sensitivity} "
                f">={self.config.nsfw_threshold:.0%}), "
                f"Korea={'on' if self.config.alert_korea else 'off'}, "
                f"Video={'on' if self.config.include_video else 'off'}"
            )
            if was_watching:
                self.scanner.begin_runtime()
                self._watching = True
                self._watch_timer.start(self.config.scan_interval * 1000)
            self.dashboard.refresh()
            self.visits_panel.refresh()
            self._update_status()

    def _on_incident_selected(self, incident: dict):
        viewer = IncidentViewer(
            incident, self, host_aliases=self.config.host_aliases,
        )
        viewer.exec()


def run_gui():
    from autolook.utils.silence import silence_third_party_noise
    silence_third_party_noise()

    app = QApplication(sys.argv)
    app.setApplicationName("AutoLook")
    app.setWindowIcon(_make_icon())
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    app.aboutToQuit.connect(window._shutdown_workers)
    window.show()
    sys.exit(app.exec())
