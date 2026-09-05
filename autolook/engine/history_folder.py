"""History folder: videos + CSV exports (not AutoLook DB)."""

from __future__ import annotations

import csv
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from autolook.engine.watcher import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from autolook.utils.event_time import parse_recording_event_time
from autolook.utils.screen_match import parse_event_time

logger = logging.getLogger(__name__)

# Net Monitor / export CSVs can embed long screenshot paths or base64 blobs.
try:
    csv.field_size_limit(min(sys.maxsize, 50 * 1024 * 1024))
except OverflowError:
    csv.field_size_limit(10 * 1024 * 1024)

_TIME_KEYS = ("time", "timestamp", "date", "datetime", "created")
_URL_KEYS = ("url", "website", "link")
_TITLE_KEYS = ("title", "windowtitle")
_CAPTION_KEYS = ("caption", "window")
_HOST_KEYS = ("computer", "host", "hostname", "pc", "ip")
_USER_KEYS = ("user", "username", "account")
_PROCESS_KEYS = ("processname", "process", "exe", "binary")
_APP_NAME_KEYS = ("applicationname", "application", "app")
_SCREEN_KEYS = ("screenshot", "image", "screen")
_KEYSTROKE_KEYS = ("keystrokes", "keys", "typed")

# "Google Chrome (chrome.exe)" or bare "chrome.exe"
_EXE_IN_PARENS = re.compile(r"\(([^()]+\.exe)\)", re.IGNORECASE)


def _norm(name: str | None) -> str:
    if name is None:
        return ""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _pick(row: dict, keys: tuple[str, ...]) -> str:
    indexed = {_norm(k): v for k, v in row.items() if k is not None}
    for key in keys:
        val = indexed.get(_norm(key))
        if val not in (None, ""):
            return str(val).strip()
    return ""


def _extract_exe(text: str) -> str:
    """Prefer process exe from 'Name (app.exe)' export style."""
    if not text:
        return ""
    m = _EXE_IN_PARENS.search(text)
    if m:
        return m.group(1).strip()
    # Bare process name
    if text.lower().endswith(".exe"):
        return text.strip()
    return text.strip()


def list_history_media(folder: Path) -> list[dict]:
    files: list[dict] = []
    if not folder.exists():
        return files
    for f in folder.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            kind = "video"
        elif ext in IMAGE_EXTENSIONS:
            kind = "image"
        else:
            continue
        if "\\tmp\\" in str(f).lower() or "/tmp/" in str(f).lower():
            continue
        files.append({
            "path": str(f),
            "type": kind,
            "mtime": os.path.getmtime(f),
            "host_hint": f.parent.name,
            "event_time": parse_recording_event_time(f),
        })
    return files


def list_history_csvs(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*.csv") if p.is_file())


def inspect_history_folder(folder: Path) -> dict:
    """Return media/csv counts and default From/To datetimes."""
    media = list_history_media(folder)
    csvs = list_history_csvs(folder)
    stamps: list[datetime] = []
    for f in media:
        ts = parse_event_time(f.get("event_time"))
        if ts:
            stamps.append(datetime.fromtimestamp(ts))
        elif f.get("mtime"):
            stamps.append(datetime.fromtimestamp(f["mtime"]))
    rows = load_history_csv_rows(folder)
    for row in rows:
        ts = parse_event_time(row.get("TIME"))
        if ts:
            stamps.append(datetime.fromtimestamp(ts))
    start = min(stamps) if stamps else datetime.now()
    end = max(stamps) if stamps else datetime.now()
    return {
        "folder": folder,
        "media": media,
        "csvs": csvs,
        "csv_rows": len(rows),
        "video_count": sum(1 for m in media if m["type"] == "video"),
        "image_count": sum(1 for m in media if m["type"] == "image"),
        "start": start,
        "end": end,
        "has_data": bool(media or csvs),
    }


def load_history_csv_rows(folder: Path) -> list[dict]:
    rows: list[dict] = []
    for path in list_history_csvs(folder):
        try:
            rows.extend(_read_csv(path))
        except Exception as e:
            logger.warning("Skipping CSV %s: %s", path.name, e)
    return rows


def _map_row(raw: dict, path: Path) -> Optional[dict]:
    """Map a Net Monitor export row into AutoLook's internal row shape."""
    name = path.name.lower()
    time_val = _pick(raw, _TIME_KEYS)
    url = _pick(raw, _URL_KEYS)
    title = _pick(raw, _TITLE_KEYS)
    caption = _pick(raw, _CAPTION_KEYS) or title
    host = _pick(raw, _HOST_KEYS)
    user = _pick(raw, _USER_KEYS)
    process = _pick(raw, _PROCESS_KEYS)
    app_name = _pick(raw, _APP_NAME_KEYS)
    screenshot = _pick(raw, _SCREEN_KEYS)
    # Keep Keystrokes on the row for optional scanning; product default skips them.
    keystrokes = _pick(raw, _KEYSTROKE_KEYS)

    # Prefer real .exe (Process Name / parenthetical) over display Application name.
    if process:
        binary = _extract_exe(process)
    elif app_name:
        binary = _extract_exe(app_name)
    else:
        binary = ""

    # Top* aggregate reports have no event time — still useful for URL/app signals.
    is_aggregate = name.startswith("top") and not time_val
    is_keylog = "keylog" in name or bool(keystrokes) or (
        bool(caption) and not url and bool(time_val) and "keystroke" in " ".join(
            _norm(k) for k in raw.keys() if k
        )
    )

    source = "keylog_csv" if is_keylog else ("aggregate_csv" if is_aggregate else "csv")

    mapped = {
        "TIME": time_val,
        "URL": url,
        "TITLE": title,
        "HOST": host,
        "USER": user,
        "BINARY": binary,
        "CAPTION": caption,
        "DESCR": "",
        "SCREENSHOT": screenshot,
        "KEYSTROKES": keystrokes,
        "_csv": str(path),
        "_source": source,
    }
    if url or binary or title or caption:
        return mapped
    return None


def _read_csv(path: Path) -> list[dict]:
    out: list[dict] = []
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, newline="", encoding=enc, errors="replace") as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)
                for raw in reader:
                    if not raw:
                        continue
                    mapped = _map_row(raw, path)
                    if mapped:
                        out.append(mapped)
            logger.info("CSV %s → %d usable row(s)", path.name, len(out))
            return out
        except UnicodeDecodeError:
            continue
        except csv.Error as e:
            logger.warning("CSV parse error in %s (%s): %s", path.name, enc, e)
            return out
        except OSError:
            return []
    return out


def filter_csv_rows(rows: list[dict], start: str, end: str) -> list[dict]:
    start_ts = parse_event_time(start)
    end_ts = parse_event_time(end)
    if start_ts is None and end_ts is None:
        return rows
    kept = []
    for row in rows:
        ts = parse_event_time(row.get("TIME"))
        if ts is None:
            # Aggregates (Top Websites / Top Apps) have no timestamp — keep them.
            if row.get("_source") == "aggregate_csv" or not row.get("TIME"):
                kept.append(row)
            continue
        if start_ts is not None and ts < start_ts:
            continue
        if end_ts is not None and ts > end_ts:
            continue
        kept.append(row)
    return kept
