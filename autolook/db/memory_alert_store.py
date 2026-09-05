"""Session-only alert store for history scans (not persisted to SQLite)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from autolook.db.incident_db import (
    ALERT_SESSION_GAP_MINUTES,
    _fmt_ts,
    _parse_ts,
)


class MemoryAlertStore:
    """In-memory NSFW/Korea alerts for history mode only."""

    def __init__(self, db_path=None):
        self._items: list[dict] = []
        self._next_id = 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._cursors = {
            "last_weblog_time": now,
            "last_applog_time": now,
            "last_keylog_time": now,
        }

    def close(self):
        pass

    def clear(self):
        self._items = []
        self._next_id = 1

    def add_incident(
        self,
        timestamp: str,
        source: str,
        detection_type: str,
        alert_level: str,
        host: str = "",
        user: str = "",
        end_timestamp: Optional[str] = None,
        confidence: Optional[float] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        app_name: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        video_source: Optional[str] = None,
        video_timestamp_sec: Optional[float] = None,
        raw_text: Optional[str] = None,
    ) -> int:
        end_ts = end_timestamp if end_timestamp not in (None, "") else timestamp
        rec = {
            "id": self._next_id,
            "timestamp": timestamp,
            "end_timestamp": end_ts,
            "host": host,
            "user": user,
            "source": source,
            "detection_type": detection_type,
            "alert_level": alert_level,
            "confidence": confidence,
            "description": description,
            "url": url,
            "app_name": app_name,
            "thumbnail_path": thumbnail_path,
            "screenshot_path": screenshot_path,
            "video_source": video_source,
            "video_timestamp_sec": video_timestamp_sec,
            "raw_text": raw_text,
        }
        self._next_id += 1
        self._items.append(rec)
        return rec["id"]

    def find_open_session(
        self,
        host: str,
        alert_level: str,
        event_time: str,
        url: Optional[str] = None,
        app_name: Optional[str] = None,
        gap_minutes: int = ALERT_SESSION_GAP_MINUTES,
    ) -> Optional[dict]:
        event_dt = _parse_ts(event_time)
        if not event_dt or gap_minutes <= 0:
            return None
        gap = timedelta(minutes=gap_minutes)
        for other in reversed(self._items):
            if (other.get("host") or "") != (host or ""):
                continue
            if (other.get("alert_level") or "") != (alert_level or ""):
                continue
            if url is not None and (other.get("url") or "") != (url or ""):
                continue
            if app_name is not None and (other.get("app_name") or "") != (app_name or ""):
                continue
            last = _parse_ts(other.get("end_timestamp") or "") or _parse_ts(
                other.get("timestamp") or ""
            )
            start = _parse_ts(other.get("timestamp") or "")
            if not last or not start:
                continue
            if event_dt < start - gap:
                continue
            if event_dt <= last + gap:
                return other
        return None

    def extend_incident(
        self,
        incident_id: int,
        event_time: str,
        confidence: Optional[float] = None,
        description: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        raw_text: Optional[str] = None,
    ) -> bool:
        event_dt = _parse_ts(event_time)
        for rec in self._items:
            if rec.get("id") != incident_id:
                continue
            start = _parse_ts(rec.get("timestamp") or "")
            end = _parse_ts(rec.get("end_timestamp") or "") or start
            if event_dt:
                if start and event_dt < start:
                    rec["timestamp"] = _fmt_ts(event_dt)
                if not end or event_dt >= end:
                    rec["end_timestamp"] = _fmt_ts(event_dt)
            if confidence is not None:
                prev = rec.get("confidence")
                try:
                    rec["confidence"] = max(float(prev or 0), float(confidence))
                except (TypeError, ValueError):
                    rec["confidence"] = confidence
            if description:
                rec["description"] = description
            if thumbnail_path:
                rec["thumbnail_path"] = thumbnail_path
            if screenshot_path:
                rec["screenshot_path"] = screenshot_path
            if raw_text:
                rec["raw_text"] = raw_text
            return True
        return False

    def merge_or_add_incident(
        self,
        timestamp: str,
        source: str,
        detection_type: str,
        alert_level: str,
        host: str = "",
        user: str = "",
        confidence: Optional[float] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        app_name: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        video_source: Optional[str] = None,
        video_timestamp_sec: Optional[float] = None,
        raw_text: Optional[str] = None,
        gap_minutes: int = ALERT_SESSION_GAP_MINUTES,
    ) -> tuple[int, bool]:
        existing = self.find_open_session(
            host=host,
            alert_level=alert_level,
            event_time=timestamp,
            url=url,
            app_name=app_name,
            gap_minutes=gap_minutes,
        )
        if existing:
            self.extend_incident(
                existing["id"],
                event_time=timestamp,
                confidence=confidence,
                description=description,
                thumbnail_path=thumbnail_path,
                screenshot_path=screenshot_path,
                raw_text=raw_text,
            )
            return int(existing["id"]), False

        new_id = self.add_incident(
            timestamp=timestamp,
            source=source,
            detection_type=detection_type,
            alert_level=alert_level,
            host=host,
            user=user,
            end_timestamp=timestamp,
            confidence=confidence,
            description=description,
            url=url,
            app_name=app_name,
            thumbnail_path=thumbnail_path,
            screenshot_path=screenshot_path,
            video_source=video_source,
            video_timestamp_sec=video_timestamp_sec,
            raw_text=raw_text,
        )
        return new_id, True

    def get_incidents(
        self,
        status: Optional[str] = None,
        alert_level: Optional[str] = None,
        user: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        rows = list(reversed(self._items))
        if alert_level:
            rows = [r for r in rows if r.get("alert_level") == alert_level]
        if user:
            rows = [r for r in rows if r.get("user") == user]
        if start or end:
            filtered = []
            for r in rows:
                ts = r.get("timestamp") or ""
                te = r.get("end_timestamp") or ts
                if start and te < start:
                    continue
                if end and ts > end:
                    continue
                filtered.append(r)
            rows = filtered
        return rows[offset: offset + limit]

    def get_scan_state(self) -> dict:
        return dict(self._cursors)

    def update_scan_state(self, **kwargs):
        for k, v in kwargs.items():
            if v is not None:
                self._cursors[k] = v

    def reset_cursors_to_now(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._cursors = {
            "last_weblog_time": now,
            "last_applog_time": now,
            "last_keylog_time": now,
        }

    def find_recent_duplicate(
        self,
        host: str,
        detection_type: str,
        event_time: str,
        url: Optional[str] = None,
        app_name: Optional[str] = None,
        within_minutes: int = 15,
    ) -> Optional[dict]:
        return self.find_open_session(
            host=host,
            alert_level=detection_type,
            event_time=event_time,
            url=url,
            app_name=app_name,
            gap_minutes=within_minutes,
        )

    def incident_count(self, status: Optional[str] = None) -> int:
        return len(self._items)
