"""Configuration management for AutoLook."""

import json
import os
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "default_config.json"
_USER_CONFIG_PATH = _PROJECT_ROOT / "config" / "user_config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively. override values win."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Config:
    """Loads default config, overlays user config, provides typed access."""

    def __init__(self, user_config_path: str | Path | None = None):
        self._path = Path(user_config_path) if user_config_path else _USER_CONFIG_PATH
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self):
        with open(_DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            self._data = json.load(f)
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                user = json.load(f)
            self._data = _deep_merge(self._data, user)

    def save(self):
        """Persist current config as user_config.json."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value

    @property
    def netmonitor_db_path(self) -> Path:
        return Path(self._data["netmonitor_db_path"])

    @property
    def recording_path(self) -> Path | None:
        p = (self._data.get("recording_path") or "").strip()
        return Path(p) if p else None

    @property
    def alert_nsfw(self) -> bool:
        return bool(self._data.get("alert_nsfw", True))

    @property
    def alert_korea(self) -> bool:
        return bool(self._data.get("alert_korea", True))

    @property
    def alert_sound(self) -> bool:
        return bool(self._data.get("alert_sound", True))

    @property
    def dedupe_minutes(self) -> int:
        return int(self._data.get("dedupe_minutes", 15))

    @property
    def media_scan_images_first(self) -> bool:
        return bool(self._data.get("media_scan_images_first", True))

    @property
    def max_new_images_per_poll(self) -> int:
        return int(self._data.get("max_new_images_per_poll", 40))

    @property
    def max_new_videos_per_poll(self) -> int:
        return int(self._data.get("max_new_videos_per_poll", 1))

    @property
    def max_video_frames(self) -> int:
        """Frames per video: 0 = full length (no cap)."""
        return int(self._data.get("max_video_frames", 0))

    @property
    def include_video(self) -> bool:
        """When True, runtime and history scan videos; images always scanned."""
        if "include_video" in self._data:
            return bool(self._data["include_video"])
        # Migrate older history-only media flag
        return bool(self._data.get("scan_media_in_history", False))

    @property
    def autolook_db_path(self) -> Path:
        p = self._data["autolook_db_path"]
        path = Path(p)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        return path

    @property
    def visits_db_path(self) -> Path:
        """SQLite file for watched web/app visit history."""
        p = self._data.get("visits_db_path", "") or ""
        if p:
            path = Path(p)
        else:
            # Default beside incidents path: data/visits.db
            path = self.autolook_db_path.parent / "visits.db"
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        return path

    @property
    def thumbnail_path(self) -> Path:
        p = self._data["thumbnail_path"]
        path = Path(p)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        return path

    @property
    def screenshot_path(self) -> Path:
        p = self._data.get("screenshot_path", "./data/screenshots")
        path = Path(p)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        return path

    @property
    def nsfw_sensitivity(self) -> str:
        return self._data.get("nsfw_sensitivity", "medium")

    @property
    def nsfw_threshold(self) -> float:
        """Minimum NSFW score (0–1) to raise an alert.

        Settings label "More alerts" stores `low` (threshold 0.2).
        "Fewer alerts" stores `high` (threshold 0.6).
        """
        level = self.nsfw_sensitivity
        key = f"nsfw_threshold_{level}"
        return float(self._data.get(key, 0.4))

    @property
    def nsfw_engine(self) -> str:
        """nudenet | opennsfw | both"""
        v = str(self._data.get("nsfw_engine", "opennsfw")).strip().lower()
        if v not in ("nudenet", "opennsfw", "both"):
            return "both"
        return v

    @property
    def ocr_hangul_min_confidence(self) -> float:
        """Minimum EasyOCR box confidence (0–1) to count Hangul."""
        try:
            v = float(self._data.get("ocr_hangul_min_confidence", 0.55))
        except (TypeError, ValueError):
            v = 0.55
        return max(0.0, min(1.0, v))

    @property
    def sample_interval(self) -> int:
        """Seconds between video frames and between screenshots (by file time)."""
        if "sample_interval_seconds" in self._data:
            return int(self._data.get("sample_interval_seconds", 3))
        return int(self._data.get("video_sample_interval_seconds", 3))

    # Back-compat alias
    @property
    def video_sample_interval(self) -> int:
        return self.sample_interval

    @property
    def watched_websites(self) -> list[str]:
        return self._data.get("watched_websites", [])

    @property
    def watched_apps(self) -> list[str]:
        return self._data.get("watched_apps", [])

    @property
    def korean_domains(self) -> list[str]:
        return self._data.get("korean_domains", [])

    @property
    def english_keywords(self) -> list[str]:
        return self._data.get("english_keywords", [])

    @property
    def custom_keywords(self) -> list[str]:
        return self._data.get("custom_keywords", [])

    @property
    def scan_interval(self) -> int:
        return self._data.get("scan_interval_seconds", 30)

    @property
    def skip_keylog_keystrokes(self) -> bool:
        return self._data.get("skip_keylog_keystrokes", True)

    @property
    def host_aliases(self) -> dict[str, str]:
        """Map of IP or hostname -> display name."""
        raw = self._data.get("host_aliases", {})
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if k and v}
