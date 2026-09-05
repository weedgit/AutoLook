"""Subsample recording images by screenshot time (Sample Rate)."""

from __future__ import annotations

import logging
from typing import Optional

from autolook.utils.event_time import parse_recording_event_time
from autolook.utils.screen_match import parse_event_time

logger = logging.getLogger(__name__)


def subsample_images_by_time(
    entries: list[dict],
    interval_sec: int,
    last_kept_ts: Optional[dict[str, float]] = None,
) -> list[dict]:
    """Keep images at least ``interval_sec`` apart by filename/event time.

    Entries are dicts with at least ``path``; optional ``host_hint`` for
    per-host continuity when ``last_kept_ts`` is provided (runtime polls).

    Sorting is by event time ascending. The first eligible image is always kept.
    """
    if not entries:
        return []
    interval = max(0, int(interval_sec))
    if interval <= 0:
        return list(entries)

    annotated: list[tuple[float, str, dict]] = []
    for e in entries:
        path = e.get("path") or ""
        host = (e.get("host_hint") or "") or "_"
        et = parse_recording_event_time(path)
        ts = parse_event_time(et)
        annotated.append((float(ts) if ts is not None else 0.0, host, e))

    annotated.sort(key=lambda x: (x[1], x[0]))

    kept: list[dict] = []
    local_last: dict[str, float] = {}
    if last_kept_ts is not None:
        local_last.update(last_kept_ts)

    for ts, host, e in annotated:
        prev = local_last.get(host)
        if prev is None or (ts - prev) >= interval:
            kept.append(e)
            local_last[host] = ts

    if last_kept_ts is not None:
        last_kept_ts.clear()
        last_kept_ts.update(local_last)

    skipped = len(entries) - len(kept)
    if skipped > 0:
        logger.info(
            f"Image sample rate {interval}s: kept {len(kept)}/{len(entries)} "
            f"(skipped {skipped})"
        )
    return kept
