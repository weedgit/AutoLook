"""Read-only access to Net Monitor's reporting.db."""

import sqlite3
from pathlib import Path
from typing import Optional


class NetMonitorDB:
    """Reads Net Monitor's reporting.db (read-only, never writes)."""

    TABLES = ("WEBLOG", "APPLOG", "KEYLOG", "KEYLOG_RESULT", "USERLOG")

    def __init__(self, db_path: Path):
        self._db_path = db_path
        if not db_path.exists():
            raise FileNotFoundError(f"Net Monitor DB not found: {db_path}")

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self._db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_weblogs(self, since: Optional[str] = None, limit: int = 1000) -> list[dict]:
        """Return WEBLOG rows, optionally filtered by TIME > since."""
        return self._query_table("WEBLOG", since, limit)

    def get_applogs(self, since: Optional[str] = None, limit: int = 1000) -> list[dict]:
        """Return APPLOG rows, optionally filtered by TIME > since."""
        return self._query_table("APPLOG", since, limit)

    def get_keylogs(self, since: Optional[str] = None, limit: int = 1000) -> list[dict]:
        """Return KEYLOG rows, optionally filtered by TIME > since."""
        return self._query_table("KEYLOG", since, limit)

    def get_userlogs(self, since: Optional[str] = None, limit: int = 1000) -> list[dict]:
        """Return USERLOG rows, optionally filtered by TIME > since."""
        return self._query_table("USERLOG", since, limit)

    def get_weblogs_range(self, start: str, end: str, limit: int = 10000) -> list[dict]:
        """Return WEBLOG rows in a time range."""
        return self._query_table_range("WEBLOG", start, end, limit)

    def get_applogs_range(self, start: str, end: str, limit: int = 10000) -> list[dict]:
        """Return APPLOG rows in a time range."""
        return self._query_table_range("APPLOG", start, end, limit)

    def get_keylogs_range(self, start: str, end: str, limit: int = 10000) -> list[dict]:
        """Return KEYLOG rows in a time range."""
        return self._query_table_range("KEYLOG", start, end, limit)

    def get_userlogs_range(self, start: str, end: str, limit: int = 10000) -> list[dict]:
        """Return USERLOG rows in a time range."""
        return self._query_table_range("USERLOG", start, end, limit)

    def _query_table(self, table: str, since: Optional[str], limit: int) -> list[dict]:
        conn = self._connect()
        try:
            if since:
                cursor = conn.execute(
                    f"SELECT * FROM {table} WHERE TIME > ? ORDER BY TIME ASC LIMIT ?",
                    (since, limit),
                )
            else:
                cursor = conn.execute(
                    f"SELECT * FROM {table} ORDER BY TIME ASC LIMIT ?",
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _query_table_range(self, table: str, start: str, end: str, limit: int) -> list[dict]:
        conn = self._connect()
        try:
            cursor = conn.execute(
                f"SELECT * FROM {table} WHERE TIME BETWEEN ? AND ? ORDER BY TIME ASC LIMIT ?",
                (start, end, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_distinct_hosts(self) -> list[str]:
        """Return sorted unique HOST values across main log tables."""
        hosts: set[str] = set()
        conn = self._connect()
        try:
            for table in ("WEBLOG", "APPLOG", "KEYLOG", "USERLOG"):
                if not self.table_exists(table):
                    continue
                col = "HOST" if table != "USERLOG" else "Host"
                try:
                    cursor = conn.execute(
                        f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL AND "{col}" != ""'
                    )
                    for row in cursor.fetchall():
                        h = (row[0] or "").strip()
                        if h:
                            hosts.add(h)
                except Exception:
                    continue
        finally:
            conn.close()
        return sorted(hosts)

    def table_exists(self, table: str) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def row_count(self, table: str) -> int:
        conn = self._connect()
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            return cursor.fetchone()[0]
        finally:
            conn.close()
