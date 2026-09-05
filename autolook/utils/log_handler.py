"""Logging handler that forwards messages to the GUI status log."""

import logging
from typing import Callable, Optional


class GuiLogHandler(logging.Handler):
    """Forwards Python log records to a GUI callback."""

    def __init__(self, callback: Callable[[str, str], None], level=logging.INFO):
        super().__init__(level)
        self._callback = callback
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord):
        try:
            level_map = {
                logging.DEBUG: "DEBUG",
                logging.INFO: "INFO",
                logging.WARNING: "WARN",
                logging.ERROR: "ERROR",
                logging.CRITICAL: "ERROR",
            }
            level = level_map.get(record.levelno, "INFO")
            self._callback(record.getMessage(), level)
        except Exception:
            self.handleError(record)


def install_gui_logging(log_panel, logger_names: Optional[list[str]] = None):
    """Attach GuiLogHandler to the autolook package logger (once)."""
    # Single parent logger avoids duplicate lines from child logger propagation
    root = logging.getLogger("autolook")
    root.setLevel(logging.INFO)

    if any(isinstance(h, GuiLogHandler) for h in root.handlers):
        return None

    handler = GuiLogHandler(log_panel.log)
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
    # Children propagate to parent; don't attach the same handler elsewhere
    return handler
