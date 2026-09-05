"""SQLite-backed NSFW/Korea alerts + scan cursors."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# If the same host+kind activity continues within this gap, extend To
# instead of creating another alert.
ALERT_SESSION_GAP_MINUTES = 15

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    end_timestamp TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT '',
    user TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    detection_type TEXT NOT NULL DEFAULT '',
    alert_level TEXT NOT NULL DEFAULT '',
    confidence REAL,
    description TEXT,
    url TEXT NOT NULL DEFAULT '',
    app_name TEXT NOT NULL DEFAULT '',
    thumbnail_path TEXT,
    screenshot_path TEXT,
    video_source TEXT,
    video_timestamp_sec REAL,
    raw_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_host_level ON alerts(host, alert_level);
CREATE INDEX IF NOT EXISTS idx_alerts_end ON alerts(end_timestamp);

CREATE TABLE IF NOT EXISTS scan_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    text = str(ts).strip().replace("T", " ")
    # Ignore bare video-second markers stored as "45"
    if text.replace(".", "", 1).isdigit() and float(text) < 1e9:
        return None
    for n in (26, 19, 16, 10):
        chunk = text[:n]
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%d-%b-%Y %H:%M:%S",
            "%d-%b-%Y %H:%M",
        ):
            try:
                sample = " ".join(chunk.split()) if "%b" in fmt else chunk
                if "%b" in fmt:
                    sample = " ".join(text.split())
                return datetime.strptime(sample if "%b" in fmt else chunk, fmt)
            except ValueError:
                continue
    return None


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class AlertStore:
    """Persisted NSFW/Korea alerts (SQLite) and runtime scan cursors."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path("./data/incidents.db")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate_legacy_schema()
        self._ensure_cursors()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def _migrate_legacy_schema(self):
        """Upgrade older incidents.db shapes (wide scan_state / incidents table)."""
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(scan_state)").fetchall()
        }
        # Old: one row with last_weblog_time, ... — New: key/value
        if cols and "value" not in cols and "last_weblog_time" in cols:
            row = self._conn.execute("SELECT * FROM scan_state LIMIT 1").fetchone()
            self._conn.execute("ALTER TABLE scan_state RENAME TO scan_state_legacy")
            self._conn.execute(
                """
                CREATE TABLE scan_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            if row:
                legacy = dict(row)
                for key in (
                    "last_weblog_time",
                    "last_applog_time",
                    "last_keylog_time",
                    "last_userlog_time",
                    "last_video_scan",
                ):
                    val = legacy.get(key)
                    if val:
                        self._conn.execute(
                            "INSERT OR REPLACE INTO scan_state (key, value) VALUES (?, ?)",
                            (key, str(val)),
                        )
            self._conn.execute("DROP TABLE IF EXISTS scan_state_legacy")
            self._conn.commit()

        # Copy legacy `incidents` rows into `alerts` once if alerts is empty
        tables = {
            r[0]
            for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "incidents" in tables:
            n_alerts = self._conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            n_old = self._conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            if n_alerts == 0 and n_old > 0:
                self._conn.execute(
                    """
                    INSERT INTO alerts (
                        timestamp, end_timestamp, host, user, source, detection_type,
                        alert_level, confidence, description, url, app_name,
                        thumbnail_path, screenshot_path, video_source,
                        video_timestamp_sec, raw_text
                    )
                    SELECT
                        timestamp,
                        COALESCE(end_timestamp, timestamp),
                        COALESCE(host, ''),
                        COALESCE(user, ''),
                        COALESCE(source, ''),
                        COALESCE(detection_type, ''),
                        COALESCE(alert_level, ''),
                        confidence,
                        description,
                        COALESCE(url, ''),
                        COALESCE(app_name, ''),
                        thumbnail_path,
                        screenshot_path,
                        video_source,
                        video_timestamp_sec,
                        raw_text
                    FROM incidents
                    """
                )
                self._conn.commit()

    def _ensure_cursors(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for key in ("last_weblog_time", "last_applog_time", "last_keylog_time"):
            row = self._conn.execute(
                "SELECT value FROM scan_state WHERE key = ?", (key,)
            ).fetchone()
            if not row:
                self._conn.execute(
                    "INSERT INTO scan_state (key, value) VALUES (?, ?)",
                    (key, now),
                )
        self._conn.commit()

    def clear(self):
        """Delete all alerts (scan cursors kept)."""
        self._conn.execute("DELETE FROM alerts")
        self._conn.commit()

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
        cur = self._conn.execute(
            """
            INSERT INTO alerts (
                timestamp, end_timestamp, host, user, source, detection_type,
                alert_level, confidence, description, url, app_name,
                thumbnail_path, screenshot_path, video_source,
                video_timestamp_sec, raw_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                end_ts,
                host or "",
                user or "",
                source or "",
                detection_type or "",
                alert_level or "",
                confidence,
                description,
                url or "",
                app_name or "",
                thumbnail_path,
                screenshot_path,
                video_source,
                video_timestamp_sec,
                raw_text,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def find_open_session(
        self,
        host: str,
        alert_level: str,
        event_time: str,
        url: Optional[str] = None,
        app_name: Optional[str] = None,
        gap_minutes: int = ALERT_SESSION_GAP_MINUTES,
    ) -> Optional[dict]:
        """Find a continuous same-kind alert to extend (same host + kind + url/app)."""
        event_dt = _parse_ts(event_time)
        if not event_dt or gap_minutes <= 0:
            return None
        cur = self._conn.execute(
            """
            SELECT * FROM alerts
            WHERE host = ? AND alert_level = ?
            ORDER BY id DESC
            LIMIT 40
            """,
            (host or "", alert_level or ""),
        )
        gap = timedelta(minutes=gap_minutes)
        for row in cur.fetchall():
            other = dict(row)
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
        """Update To (and optional latest evidence) on an existing alert."""
        row = self._conn.execute(
            "SELECT * FROM alerts WHERE id = ?", (int(incident_id),)
        ).fetchone()
        if not row:
            return False
        rec = dict(row)
        event_dt = _parse_ts(event_time)
        start = _parse_ts(rec.get("timestamp") or "")
        end = _parse_ts(rec.get("end_timestamp") or "") or start
        new_from = rec.get("timestamp") or event_time
        new_to = rec.get("end_timestamp") or event_time
        if event_dt:
            if start and event_dt < start:
                new_from = _fmt_ts(event_dt)
            if not end or event_dt >= end:
                new_to = _fmt_ts(event_dt)

        new_conf = rec.get("confidence")
        if confidence is not None:
            try:
                new_conf = max(float(new_conf or 0), float(confidence))
            except (TypeError, ValueError):
                new_conf = confidence

        self._conn.execute(
            """
            UPDATE alerts SET
                timestamp = ?,
                end_timestamp = ?,
                confidence = ?,
                description = COALESCE(?, description),
                thumbnail_path = COALESCE(?, thumbnail_path),
                screenshot_path = COALESCE(?, screenshot_path),
                raw_text = COALESCE(?, raw_text)
            WHERE id = ?
            """,
            (
                new_from,
                new_to,
                new_conf,
                description,
                thumbnail_path,
                screenshot_path,
                raw_text,
                int(incident_id),
            ),
        )
        self._conn.commit()
        return True

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
        """One continuous visit → one alert; To moves forward.

        Returns (incident_id, is_new).
        """
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
        sql = "SELECT * FROM alerts"
        params: list = []
        clauses = []
        if alert_level:
            clauses.append("alert_level = ?")
            params.append(alert_level)
        if user:
            clauses.append("user = ?")
            params.append(user)
        # Overlap: alert From..To intersects [start, end]
        if start:
            clauses.append("COALESCE(end_timestamp, timestamp) >= ?")
            params.append(start)
        if end:
            clauses.append("timestamp <= ?")
            params.append(end)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur = self._conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def get_scan_state(self) -> dict:
        cur = self._conn.execute("SELECT key, value FROM scan_state")
        return {r["key"]: r["value"] for r in cur.fetchall()}

    def update_scan_state(self, **kwargs):
        for k, v in kwargs.items():
            if v is None:
                continue
            self._conn.execute(
                """
                INSERT INTO scan_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (k, str(v)),
            )
        self._conn.commit()

    def reset_cursors_to_now(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.update_scan_state(
            last_weblog_time=now,
            last_applog_time=now,
            last_keylog_time=now,
        )

    def find_recent_duplicate(
        self,
        host: str,
        detection_type: str,
        event_time: str,
        url: Optional[str] = None,
        app_name: Optional[str] = None,
        within_minutes: int = 15,
    ) -> Optional[dict]:
        """Deprecated alias — prefer find_open_session / merge_or_add_incident."""
        return self.find_open_session(
            host=host,
            alert_level=detection_type,
            event_time=event_time,
            url=url,
            app_name=app_name,
            gap_minutes=within_minutes,
        )

    def incident_count(self, status: Optional[str] = None) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()
        return int(row["n"] if row else 0)


# Keep old name so existing imports continue to work.
IncidentDB = AlertStore
