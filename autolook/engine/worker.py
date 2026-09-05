"""Background worker thread for scanning without blocking the GUI."""

import logging
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from autolook.engine.scanner import Scanner

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    """Runs scanner.scan_new() in a background thread."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, scanner: Scanner, parent=None):
        super().__init__(parent)
        self.scanner = scanner

    def run(self):
        try:
            incidents = self.scanner.scan_new()
            self.finished.emit(incidents)
        except Exception as e:
            logger.error(f"ScanWorker error: {e}\n{traceback.format_exc()}")
            self.error.emit(str(e))


class HistoryScanWorker(QThread):
    """Runs scanner.scan_history_folder() in a background thread."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        scanner: Scanner,
        folder: str,
        start: str,
        end: str,
        parent=None,
    ):
        super().__init__(parent)
        self.scanner = scanner
        self.folder = folder
        self.start_date = start
        self.end_date = end
        self.was_stopped = False

    def stop(self) -> None:
        """Request cooperative cancel of the history scan."""
        self.was_stopped = True
        self.scanner.request_cancel()
        self.requestInterruption()

    def run(self):
        try:
            video_note = (
                "images + video"
                if self.scanner.config.include_video
                else "images only (video off)"
            )
            self.progress.emit(
                f"History ({video_note}): {self.start_date} → {self.end_date}"
            )
            incidents = self.scanner.scan_history_folder(
                self.folder,
                self.start_date,
                self.end_date,
            )
            if self.was_stopped or self.scanner.is_cancelled():
                self.was_stopped = True
                self.progress.emit(
                    f"History stopped ({len(incidents)} alert(s) kept)"
                )
            self.finished.emit(incidents)
        except Exception as e:
            logger.error(f"HistoryScanWorker error: {e}\n{traceback.format_exc()}")
            self.error.emit(str(e))
