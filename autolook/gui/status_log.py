"""Resizable status log panel for AutoLook runtime messages."""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor, QColor, QTextCharFormat, QFont

LEVEL_COLORS = {
    "INFO": QColor(200, 220, 255),
    "WARN": QColor(255, 220, 120),
    "ERROR": QColor(255, 140, 140),
    "DEBUG": QColor(160, 160, 160),
    "SUCCESS": QColor(140, 255, 160),
}


class StatusLogPanel(QWidget):
    """Right-side panel showing AutoLook running status log."""

    message_added = pyqtSignal(str, str)  # level, text — thread-safe append
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(180)
        self._build_ui()
        self.message_added.connect(self._append_message)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("Status Log")
        title.setStyleSheet("font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setFixedWidth(60)
        self._btn_clear.setToolTip(
            "Clear alert / visit tables and this log.\n"
            "Does not delete database records.\n"
            "New detections will appear from the clear time."
        )
        self._btn_clear.clicked.connect(self.clear_requested.emit)
        header.addWidget(self._btn_clear)
        layout.addLayout(header)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4; border: 1px solid #444; }"
        )
        layout.addWidget(self._text)

    def log(self, message: str, level: str = "INFO"):
        """Append a log line. Safe to call from any thread."""
        self.message_added.emit(level.upper(), message)

    def _append_message(self, level: str, message: str):
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] [{level}] {message}"

            color = LEVEL_COLORS.get(level, LEVEL_COLORS["INFO"])
            fmt = QTextCharFormat()
            fmt.setForeground(color)

            cursor = self._text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(line + "\n", fmt)
            self._text.setTextCursor(cursor)
            self._text.ensureCursorVisible()
        except RuntimeError:
            pass

    def clear(self):
        self._text.clear()
