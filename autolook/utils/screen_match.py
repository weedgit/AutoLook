"""Match Net Monitor recording JPGs to log events by host + time."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from autolook.utils.host_names import hostname_to_ip, looks_like_ip

_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%d.%m.%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",
    # Net Monitor report export: "09-Aug-2026   00:00:12"
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y %H:%M",
    "%d/%b/%Y %H:%M:%S",
)


def parse_event_time(value: str | None) -> Optional[float]:
    """Parse Net Monitor TIME string to unix timestamp."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Numeric epoch (seconds or ms)
    if re.fullmatch(r"\d+(\.\d+)?", text):
        ts = float(text)
        if ts > 1e12:  # milliseconds
            ts /= 1000.0
        return ts
    # Collapse odd spacing from CSV exports
    text = re.sub(r"\s+", " ", text).strip()
    # Drop fractional seconds: 2026-08-09T21:17:16.851
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\.\d+", text):
        text = text[:19].replace("T", " ")
    for fmt in _TIME_FORMATS:
        try:
            sample = text[:19] if "T" not in fmt and "%b" not in fmt else text
            if "%b" in fmt:
                sample = text  # day-Mon-year needs full string
            return datetime.strptime(sample, fmt).timestamp()
        except ValueError:
            continue
    return None


def resolve_recording_folder(recording_path: Path | None, host: str) -> Optional[Path]:
    """Find recordings/<ip> folder for a log HOST (hostname or IP)."""
    if not recording_path or not recording_path.exists() or not host:
        return None
    host = host.strip()
    candidates: list[str] = []
    if looks_like_ip(host):
        candidates.append(host)
    else:
        ip = hostname_to_ip(host)
        if ip:
            candidates.append(ip)
        # Also try exact folder name match (hostname folders are rare but possible)
        candidates.append(host)

    for name in candidates:
        folder = recording_path / name
        if folder.is_dir():
            return folder
    return None


def find_nearest_screen_image(
    recording_path: Path | None,
    host: str,
    event_time: str | None,
    max_delta_sec: float = 300.0,
) -> Optional[str]:
    """Return path to nearest .jpg/.png near event_time for this host.

    Used when WEBLOG/APPLOG have empty SCREENSHOT but Net Monitor still
    saved periodic screen captures under recordings/<ip>/.
    """
    folder = resolve_recording_folder(recording_path, host)
    if not folder:
        return None

    target = parse_event_time(event_time)
    best_path: Optional[str] = None
    best_delta = float("inf")

    for f in folder.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
            continue
        try:
            mtime = os.path.getmtime(f)
        except OSError:
            continue
        if target is None:
            # No usable time — take newest file once
            if best_path is None or mtime > best_delta:
                best_path = str(f)
                best_delta = mtime
            continue
        delta = abs(mtime - target)
        if delta < best_delta:
            best_delta = delta
            best_path = str(f)

    if target is None:
        return best_path
    if best_path is not None and best_delta <= max_delta_sec:
        return best_path
    return None
