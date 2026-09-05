"""Format From~To time ranges for tables."""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def _parse(ts: str | None) -> Optional[datetime]:
    if not ts:
        return None
    text = str(ts).strip().replace("T", " ")
    for fmt, n in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        try:
            return datetime.strptime(text[:n], fmt)
        except ValueError:
            continue
    return None


def format_from_to(start: str | None, end: str | None = None) -> str:
    """Combine From/To for display.

    Same moment: ``2026-09-03 11:38:40``
    Same day:    ``2026-09-03 11:38:40 ~ 12:25:46``
    Other days:  ``2026-09-03 11:38:40 ~ 2026-09-04 09:01:02``
    """
    start_s = (start or "").strip()
    end_s = (end or "").strip() or start_s
    if not start_s:
        return end_s[:19] if end_s else ""
    if not end_s or end_s == start_s:
        return start_s[:19]

    # Legacy video-second markers
    if end_s.replace(".", "", 1).isdigit() and float(end_s) < 1e9:
        return f"{start_s[:19]} (+{end_s}s)"

    a = _parse(start_s)
    b = _parse(end_s)
    if not a or not b:
        if len(start_s) >= 10 and end_s.startswith(start_s[:10]) and len(end_s) >= 19:
            return f"{start_s[:19]} ~ {end_s[11:19]}"
        return f"{start_s[:19]} ~ {end_s[:19]}"

    left = a.strftime("%Y-%m-%d %H:%M:%S")
    if a.date() == b.date():
        if a == b:
            return left
        return f"{left} ~ {b.strftime('%H:%M:%S')}"
    return f"{left} ~ {b.strftime('%Y-%m-%d %H:%M:%S')}"
