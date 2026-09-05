"""Ask admin for a time period (folder scan or saved DB history)."""

from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QDateTimeEdit, QDialogButtonBox,
    QLabel,
)
from PyQt6.QtCore import QDate, QDateTime, QTime


class PeriodDialog(QDialog):
    def __init__(
        self,
        start: datetime,
        end: datetime,
        parent=None,
        *,
        title: str = "History period",
        hint: str = "",
        ok_text: str = "Watch",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        if not hint:
            hint = (
                "Default range is the start and end of files in this folder.\n"
                "Change From / To if you only want part of it, then Watch.\n"
                "All images in range are sampled at Sample Rate; videos follow Settings → Include video."
            )
        hint_lbl = QLabel(hint)
        hint_lbl.setWordWrap(True)
        layout.addWidget(hint_lbl)

        form = QFormLayout()
        self._from = QDateTimeEdit()
        self._from.setCalendarPopup(True)
        self._from.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self._from.setDateTime(_qdt(start))
        form.addRow("From:", self._from)

        self._to = QDateTimeEdit()
        self._to.setCalendarPopup(True)
        self._to.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self._to.setDateTime(_qdt(end))
        form.addRow("To:", self._to)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def period(self) -> tuple[str, str]:
        start = self._from.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        end = self._to.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        return start, end


def _qdt(dt: datetime) -> QDateTime:
    return QDateTime(
        QDate(dt.year, dt.month, dt.day),
        QTime(dt.hour, dt.minute, dt.second),
    )
