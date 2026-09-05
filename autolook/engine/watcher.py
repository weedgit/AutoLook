"""Live mode: poll DB and watch recording folder for new files."""

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mpeg", ".mpg", ".avi", ".mkv", ".webm", ".mov"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


class RecordingWatcher:
    """Watches a recording folder for new video/image files."""

    def __init__(self, recording_path: Path):
        self._path = recording_path
        self._known_files: set[str] = set()
        self._initialized = False

    def initialize(self):
        """Snapshot current files so we only detect new ones."""
        if not self._path.exists():
            logger.warning(f"Recording path does not exist: {self._path}")
            self._initialized = True
            return
        self._known_files = set()
        for f in self._path.rglob("*"):
            if f.is_file() and f.suffix.lower() in (VIDEO_EXTENSIONS | IMAGE_EXTENSIONS):
                self._known_files.add(str(f))
        self._initialized = True
        logger.info(f"Initialized watcher with {len(self._known_files)} existing files in {self._path}")

    def get_new_files(self, images_first: bool = True) -> list[dict]:
        """Return unseen media files (does not mark them seen).

        Call ``mark_seen`` after a file is scanned or intentionally skipped
        (e.g. sample-rate). Files left unseen (poll limit deferral) stay
        eligible for the next poll.
        """
        if not self._initialized:
            self.initialize()

        if not self._path.exists():
            return []

        images: list[dict] = []
        videos: list[dict] = []
        for f in self._path.rglob("*"):
            if not f.is_file():
                continue
            fstr = str(f)
            if fstr in self._known_files:
                continue
            # Skip Net Monitor temp folders
            if "\\tmp\\" in fstr.lower() or "/tmp/" in fstr.lower():
                continue
            ext = f.suffix.lower()
            entry = {
                "path": fstr,
                "type": "video" if ext in VIDEO_EXTENSIONS else "image",
                "ext": ext,
                "mtime": os.path.getmtime(f),
                "host_hint": self._host_hint_from_path(f),
            }
            if ext in VIDEO_EXTENSIONS:
                videos.append(entry)
            elif ext in IMAGE_EXTENSIONS:
                images.append(entry)

        images.sort(key=lambda x: x["mtime"])
        videos.sort(key=lambda x: x["mtime"])
        if images_first:
            return images + videos
        return videos + images

    def mark_seen(self, paths: list[str] | set[str]) -> None:
        """Remember paths so they are not returned again by get_new_files."""
        for p in paths:
            if p:
                self._known_files.add(str(p))

    def scan_all(self, images_first: bool = True) -> list[dict]:
        """Return all video/image files (for history mode)."""
        if not self._path.exists():
            return []
        images: list[dict] = []
        videos: list[dict] = []
        for f in self._path.rglob("*"):
            if not f.is_file():
                continue
            fstr = str(f)
            if "\\tmp\\" in fstr.lower() or "/tmp/" in fstr.lower():
                continue
            ext = f.suffix.lower()
            entry = {
                "path": fstr,
                "type": "video" if ext in VIDEO_EXTENSIONS else "image",
                "ext": ext,
                "mtime": os.path.getmtime(f),
                "host_hint": self._host_hint_from_path(f),
            }
            if ext in VIDEO_EXTENSIONS:
                videos.append(entry)
            elif ext in IMAGE_EXTENSIONS:
                images.append(entry)

        images.sort(key=lambda x: x["mtime"], reverse=True)
        videos.sort(key=lambda x: x["mtime"], reverse=True)
        if images_first:
            return images + videos
        return videos + images

    def filter_by_mtime_range(
        self,
        files: list[dict],
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Filter files by modification time using date strings YYYY-MM-DD[ HH:MM:SS]."""
        start_ts = self._parse_bound(start, end_of_day=False)
        end_ts = self._parse_bound(end, end_of_day=True)
        result = []
        for f in files:
            mtime = f.get("mtime") or os.path.getmtime(f["path"])
            if start_ts is not None and mtime < start_ts:
                continue
            if end_ts is not None and mtime > end_ts:
                continue
            result.append(f)
        return result

    @staticmethod
    def _parse_bound(value: str | None, end_of_day: bool) -> float | None:
        if not value:
            return None
        text = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text[:19] if "T" in text or " " in text else text[:10], fmt)
                if fmt == "%Y-%m-%d" and end_of_day:
                    dt = dt.replace(hour=23, minute=59, second=59)
                return dt.timestamp()
            except ValueError:
                continue
        return None

    @staticmethod
    def _host_hint_from_path(path: Path) -> str:
        """Net Monitor stores files under recordings/<ip>/filename."""
        parent = path.parent.name
        return parent
