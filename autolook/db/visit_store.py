"""Watched web/app visit history — persisted in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from autolook.db.incident_db import ALERT_SESSION_GAP_MINUTES, _fmt_ts, _parse_ts


# Friendly Source column labels
_SOURCE_LABELS = {
    "youtube.com": "YouTube",
    "facebook.com": "Facebook",
    "x.com": "X (Twitter)",
    "twitter.com": "Twitter",
    "discord.com": "Discord",
    "discord.gg": "Discord",
    "discord.exe": "Discord",
    "telegram.org": "Telegram",
    "web.telegram.org": "Telegram",
    "telegram.exe": "Telegram",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "reddit.com": "Reddit",
    "line.me": "LINE",
    "line.exe": "LINE",
    "kakaotalk.exe": "KakaoTalk",
    "slack.exe": "Slack",
    "slack.com": "Slack",
    "whatsapp.exe": "WhatsApp",
    "web.whatsapp.com": "WhatsApp",
    "whatsapp.com": "WhatsApp",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    end_timestamp TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT '',
    user TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    matched TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    app_name TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_visits_host_source ON visits(host, source);
CREATE INDEX IF NOT EXISTS idx_visits_end ON visits(end_timestamp);
"""


def source_label(matched: str, kind: str = "") -> str:
    """Human label for watched match (facebook.com → Facebook)."""
    key = (matched or "").lower().strip()
    if key in _SOURCE_LABELS:
        return _SOURCE_LABELS[key]
    base = key.replace(".exe", "").replace(".com", "").replace(".org", "")
    if base:
        return base[:1].upper() + base[1:]
    return matched or kind or "Unknown"


class VisitStore:
    """SQLite-backed watched web/app visit sessions (From / To / Name / Source)."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def clear(self):
        """Delete all visit rows (use with care)."""
        self._conn.execute("DELETE FROM visits")
        self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM visits").fetchone()
        return int(row["n"] if row else 0)

    def get_visits(
        self,
        limit: int = 50000,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> list[dict]:
        sql = "SELECT * FROM visits"
        params: list = []
        clauses = []
        if start:
            clauses.append("COALESCE(end_timestamp, timestamp) >= ?")
            params.append(start)
        if end:
            clauses.append("timestamp <= ?")
            params.append(end)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = self._conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def record_visit(
        self,
        timestamp: str,
        host: str,
        source: str,
        kind: str,
        matched: str = "",
        url: str = "",
        app_name: str = "",
        user: str = "",
        gap_minutes: int = ALERT_SESSION_GAP_MINUTES,
    ) -> tuple[int, bool]:
        """Record or extend a watched visit. Returns (id, is_new)."""
        if not timestamp or not source:
            return 0, False

        event_dt = _parse_ts(timestamp)
        existing = self._find_open(
            host=host,
            source=source,
            event_dt=event_dt,
            gap_minutes=gap_minutes,
        )
        if existing and event_dt:
            start = _parse_ts(existing.get("timestamp") or "")
            last = _parse_ts(existing.get("end_timestamp") or "") or start
            new_from = existing.get("timestamp") or timestamp
            new_to = existing.get("end_timestamp") or timestamp
            if start and event_dt < start:
                new_from = _fmt_ts(event_dt)
            if not last or event_dt >= last:
                new_to = _fmt_ts(event_dt)
            self._conn.execute(
                """
                UPDATE visits
                SET timestamp = ?, end_timestamp = ?,
                    url = CASE WHEN ? != '' THEN ? ELSE url END,
                    app_name = CASE WHEN ? != '' THEN ? ELSE app_name END,
                    user = CASE WHEN ? != '' THEN ? ELSE user END
                WHERE id = ?
                """,
                (
                    new_from,
                    new_to,
                    url or "",
                    url or "",
                    app_name or "",
                    app_name or "",
                    user or "",
                    user or "",
                    int(existing["id"]),
                ),
            )
            self._conn.commit()
            return int(existing["id"]), False

        cur = self._conn.execute(
            """
            INSERT INTO visits (
                timestamp, end_timestamp, host, user, source, kind,
                matched, url, app_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                timestamp,
                host or "",
                user or "",
                source,
                kind or "",
                matched or "",
                url or "",
                app_name or "",
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid), True

    def _find_open(
        self,
        host: str,
        source: str,
        event_dt: Optional[datetime],
        gap_minutes: int,
    ) -> Optional[dict]:
        if not event_dt or gap_minutes <= 0:
            return None
        # Look at recent same host+source rows (newest first)
        cur = self._conn.execute(
            """
            SELECT * FROM visits
            WHERE host = ? AND source = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (host or "", source or ""),
        )
        gap = timedelta(minutes=gap_minutes)
        for row in cur.fetchall():
            other = dict(row)
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
