"""Parse event times from Net Monitor recording filenames / file mtime."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# Administrator_2026-09-03_11_10_52-1-0-0-780-438....jpg
_NM_STAMP = re.compile(
    r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})[_-](?P<H>\d{2})[_-](?P<M>\d{2})[_-](?P<S>\d{2})"
)


def is_iso_timestamp(value: str | None) -> bool:
    if not value:
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", value.strip()))


def format_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_recording_event_time(
    path: str | Path,
    fallback_timestamp: str = "",
) -> str:
    """Return ISO-like event time for a recording file.

    Prefer embedded Net Monitor stamp in the filename, then an already-ISO
    fallback, then file modification time.
    """
    if fallback_timestamp and is_iso_timestamp(fallback_timestamp):
        return fallback_timestamp.strip()[:19]

    name = Path(path).stem
    m = _NM_STAMP.search(name)
    if m:
        try:
            dt = datetime(
                int(m.group("y")),
                int(m.group("m")),
                int(m.group("d")),
                int(m.group("H")),
                int(m.group("M")),
                int(m.group("S")),
            )
            return format_ts(dt)
        except ValueError:
            pass

    try:
        return format_ts(datetime.fromtimestamp(os.path.getmtime(path)))
    except OSError:
        return format_ts(datetime.now())
