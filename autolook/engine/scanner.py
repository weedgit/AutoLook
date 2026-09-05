"""Scan engine: processes Net Monitor data through detection pipeline."""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from autolook.config import Config
from autolook.db.netmonitor_db import NetMonitorDB
from autolook.db.incident_db import IncidentDB
from autolook.db.visit_store import VisitStore, source_label
from autolook.detection.text_detector import TextDetector
from autolook.detection.domain_app_detector import DomainAppDetector
from autolook.detection.nsfw_detector import NSFWDetector
from autolook.detection.alert_scorer import AlertScorer
from autolook.engine.frame_extractor import extract_frames
from autolook.engine.history_folder import (
    filter_csv_rows,
    list_history_media,
    load_history_csv_rows,
)
from autolook.engine.watcher import RecordingWatcher
from autolook.utils.thumbnail import save_incident_images
from autolook.utils.screen_match import find_nearest_screen_image, parse_event_time
from autolook.utils.event_time import parse_recording_event_time
from autolook.utils.ignore_sites import (
    is_google_translate_context,
    strip_korea_detections,
)
from autolook.utils.media_sample import subsample_images_by_time

logger = logging.getLogger(__name__)


class Scanner:
    """Processes Net Monitor DB rows through text/domain/app/NSFW detection."""

    def __init__(
        self,
        config: Config,
        nm_db: NetMonitorDB,
        inc_db: IncidentDB,
        visit_store: VisitStore | None = None,
    ):
        self.config = config
        self.nm_db = nm_db
        self.inc_db = inc_db
        self.visit_store = visit_store if visit_store is not None else VisitStore(
            config.visits_db_path
        )
        self.text_detector = TextDetector(
            english_keywords=config.english_keywords,
            custom_keywords=config.custom_keywords,
        )
        self.domain_app_detector = DomainAppDetector(
            watched_websites=config.watched_websites,
            watched_apps=config.watched_apps,
            korean_domains=config.korean_domains,
        )
        self.nsfw_detector = NSFWDetector(
            threshold=config.nsfw_threshold,
            engine=config.nsfw_engine,
        )
        logger.info(
            "NSFW engine=%s  sensitivity=%s  min score=%.0f%%",
            config.nsfw_engine,
            config.nsfw_sensitivity,
            config.nsfw_threshold * 100,
        )
        # Hangul / keywords: Net Monitor weblog, applog, keylog text only (no screen OCR)
        self.alert_scorer = AlertScorer()
        rec = config.recording_path
        self.recording_watcher = RecordingWatcher(rec) if rec and rec.exists() else None
        self._history_folder: Path | None = None
        self._cancel = threading.Event()
        # Per-host last kept image timestamp (unix) for runtime Sample Rate
        self._last_image_sample_ts: dict[str, float] = {}
        # Watched visits: only during runtime (from AutoLook start), not history
        self._record_visits = True
        if self.recording_watcher:
            logger.info(f"Recording path: {rec}")
        else:
            logger.warning("Recording path not set or missing — video/screenshot scan disabled")

    def request_cancel(self) -> None:
        """Ask the current history (or long) scan to stop cooperatively."""
        self._cancel.set()

    def clear_cancel(self) -> None:
        self._cancel.clear()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def scan_new(self) -> list[dict]:
        """Poll for new rows since last scan, run detection, save incidents."""
        state = self.inc_db.get_scan_state()
        incidents = []

        n_web, web_incs = self._scan_weblogs(state.get("last_weblog_time"))
        incidents += web_incs
        n_app, app_incs = self._scan_applogs(state.get("last_applog_time"))
        incidents += app_incs
        n_key, key_incs = self._scan_keylogs(state.get("last_keylog_time"))
        incidents += key_incs

        n_rec = 0
        if self.recording_watcher:
            n_rec, rec_incs = self._scan_new_recordings()
            incidents += rec_incs

        # Always log so Status Log shows the watch is alive every poll
        parts = []
        if n_web:
            parts.append(f"{n_web} weblog")
        if n_app:
            parts.append(f"{n_app} applog")
        if n_key:
            parts.append(f"{n_key} keylog")
        if n_rec:
            parts.append(f"{n_rec} recording")
        if parts:
            logger.info(
                f"Watching OK — new: {', '.join(parts)} → {len(incidents)} alert(s)"
            )
        else:
            logger.info("Watching OK — no new data this poll")

        return incidents

    def begin_runtime(self):
        """Start live watch: only new NM DB rows and new recording files."""
        self.inc_db.reset_cursors_to_now()
        self._last_image_sample_ts.clear()
        self._record_visits = True
        # Watched visits: keep SQLite history; runtime UI filters from this start
        self._visits_session_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(
            "Watched visits session start %s — new visits saved; older rows kept in DB",
            self._visits_session_start,
        )
        rec = self.config.recording_path
        self.recording_watcher = RecordingWatcher(rec) if rec and rec.exists() else None
        if self.recording_watcher:
            self.recording_watcher.initialize()
            n = len(self.recording_watcher._known_files)
            logger.info(f"Runtime watch — {n} existing recording file(s) in {rec}")
            logger.info("New recordings after this time will be listed in the status log")
        else:
            logger.warning("Recording path not set — video/screenshot scan disabled")

    def scan_history_folder(
        self,
        folder: str | Path,
        start: str,
        end: str,
    ) -> list[dict]:
        """History mode: CSV logs + sampled images; videos if include_video is on.

        Sample Rate applies to both: images by screenshot time in the filename,
        videos full length at the same interval (no frame cap).
        Watched visits are not saved during history (runtime-only).
        """
        folder = Path(folder)
        incidents: list[dict] = []
        self._history_folder = folder
        self.clear_cancel()
        prev_record_visits = self._record_visits
        self._record_visits = False

        try:
            return self._scan_history_folder_body(folder, start, end, incidents)
        finally:
            self._record_visits = prev_record_visits
            self._history_folder = None

    def _scan_history_folder_body(
        self,
        folder: Path,
        start: str,
        end: str,
        incidents: list[dict],
    ) -> list[dict]:
        rows = filter_csv_rows(load_history_csv_rows(folder), start, end)
        logger.info(f"History CSV rows in period: {len(rows)}")
        for row in rows:
            if self.is_cancelled():
                break
            src = row.get("_source") or ""
            if src == "keylog_csv":
                # Caption only — Keystrokes never scanned (typing Korean is allowed).
                inc = self._process_keylog(row)
            elif row.get("URL"):
                inc = self._process_weblog(row)
            else:
                inc = self._process_applog(row)
            if inc:
                incidents.append(inc)

        if self.is_cancelled():
            logger.info(f"History scan stopped: {len(incidents)} alert(s) so far")
            return incidents

        media = list_history_media(folder)
        watcher = RecordingWatcher(folder)
        media = watcher.filter_by_mtime_range(media, start, end)
        sample_interval = self.config.sample_interval
        images_all = [f for f in media if f["type"] == "image"]
        images = subsample_images_by_time(images_all, sample_interval)
        videos = (
            [f for f in media if f["type"] == "video"]
            if self.config.include_video
            else []
        )
        if self.config.include_video:
            logger.info(
                f"History media: {len(images)}/{len(images_all)} image(s) "
                f"(sample {sample_interval}s), {len(videos)} video(s) "
                f"(1 frame / {sample_interval}s, full length)"
            )
        else:
            logger.info(
                f"History media: {len(images)}/{len(images_all)} image(s) "
                f"(sample {sample_interval}s), videos skipped (Include video off)"
            )

        for i, f in enumerate(images, 1):
            if self.is_cancelled():
                break
            logger.info(f"History image {i}/{len(images)}: {Path(f['path']).name}")
            inc = self.scan_screenshot(f["path"], host=f.get("host_hint", ""))
            if inc:
                incidents.append(inc)
        for i, f in enumerate(videos, 1):
            if self.is_cancelled():
                break
            logger.info(f"History video {i}/{len(videos)}: {Path(f['path']).name}")
            incidents += self.scan_video(
                f["path"],
                host=f.get("host_hint", ""),
                sample_interval=sample_interval,
            )

        if self.is_cancelled():
            logger.info(f"History scan stopped: {len(incidents)} alert(s) so far")
        else:
            logger.info(f"History scan complete: {len(incidents)} alert(s)")
        return incidents

    def scan_screenshot(
        self,
        image_path: str,
        host: str = "",
        timestamp: str = "",
    ) -> Optional[dict]:
        """Run NSFW detection on a screenshot (no OCR).

        Hangul / keywords come from Net Monitor weblog, applog, and keylog
        captions — not from screen OCR.
        """
        if not Path(image_path).exists():
            return None

        detections = []
        nsfw = self.nsfw_detector.detect_file(image_path)
        if nsfw:
            detections.append(nsfw)

        if not detections:
            return None

        alert = self.alert_scorer.score(detections)
        if not alert:
            return None
        if not self._kind_enabled(alert):
            return None

        event_time = parse_recording_event_time(image_path, timestamp)
        thumb, screen = self._attach_images(image_path)

        inc_id, is_new = self.inc_db.merge_or_add_incident(
            timestamp=event_time,
            host=host,
            source="screenshot",
            detection_type=alert["detection_type"],
            alert_level=alert["alert_level"],
            confidence=alert.get("confidence"),
            description=alert["description"],
            thumbnail_path=thumb,
            screenshot_path=screen,
            raw_text=str(nsfw.get("labels", []) if nsfw else ""),
        )
        alert["incident_id"] = inc_id
        alert["source"] = "screenshot"
        alert["host"] = host
        alert["file_name"] = Path(image_path).name
        alert["merged"] = not is_new
        return alert

    def scan_video(
        self,
        video_path: str,
        host: str = "",
        sample_interval: int | None = None,
        max_frames: int | None = None,
    ) -> list[dict]:
        """Extract frames and run NSFW only (no OCR on video).

        Hangul / keywords are detected from Net Monitor text logs
        (weblog / applog / keylog), not from video frames.
        """
        interval = (
            self.config.sample_interval
            if sample_interval is None
            else int(sample_interval)
        )
        if max_frames is None:
            frames_cap = int(self.config.max_video_frames)
        else:
            frames_cap = int(max_frames)
        logger.info(
            "Video scan %s — interval=%ss cap=%s NSFW only (no OCR)",
            Path(video_path).name,
            interval,
            "full" if frames_cap <= 0 else frames_cap,
        )
        frames = extract_frames(
            video_path,
            interval_seconds=interval,
            max_frames=frames_cap,
            cancel_check=self.is_cancelled,
        )
        if not frames:
            return []

        incidents = []
        current_group: Optional[dict] = None

        for frame in frames:
            if self.is_cancelled():
                break
            frame_detections = []
            nsfw = self.nsfw_detector.detect_file(frame["path"])
            if nsfw:
                frame_detections.append(nsfw)

            if not frame_detections:
                if current_group:
                    saved = self._save_video_incident(current_group, video_path, host)
                    if saved:
                        incidents.append(saved)
                    current_group = None
                continue

            best_conf = max(
                (d.get("confidence", 0.5) for d in frame_detections), default=0.5
            )
            if current_group is None:
                current_group = {
                    "start_sec": frame["timestamp_sec"],
                    "end_sec": frame["timestamp_sec"],
                    "best_frame": frame["path"],
                    "best_confidence": best_conf,
                    "detections": frame_detections,
                }
            else:
                current_group["end_sec"] = frame["timestamp_sec"]
                if best_conf > current_group["best_confidence"]:
                    current_group["best_frame"] = frame["path"]
                    current_group["best_confidence"] = best_conf
                current_group["detections"].extend(frame_detections)

        if current_group and not self.is_cancelled():
            saved = self._save_video_incident(current_group, video_path, host)
            if saved:
                incidents.append(saved)

        for frame in frames:
            try:
                Path(frame["path"]).unlink(missing_ok=True)
            except Exception:
                pass

        return incidents

    def _save_video_incident(self, group: dict, video_path: str, host: str = "") -> Optional[dict]:
        alert = self.alert_scorer.score(group["detections"])
        if not alert or not self._kind_enabled(alert):
            return None

        thumb, screen = save_incident_images(
            group["best_frame"],
            self.config.thumbnail_path,
            self.config.screenshot_path,
        )

        types = {d.get("type") for d in group["detections"]}
        has_korean = bool(types & {"hangul", "english_keyword", "custom_keyword", "korean_domain"})
        has_nsfw = "nsfw" in types
        if has_korean and has_nsfw:
            desc = f"Korea + NSFW in video ({group['start_sec']:.0f}s-{group['end_sec']:.0f}s)"
        elif has_korean:
            desc = f"Korea text in video ({group['start_sec']:.0f}s-{group['end_sec']:.0f}s)"
        else:
            desc = f"NSFW in video ({group['start_sec']:.0f}s-{group['end_sec']:.0f}s)"

        from datetime import datetime
        from autolook.utils.screen_match import parse_event_time

        base = parse_recording_event_time(video_path)
        base_ts = parse_event_time(base)
        if base_ts is not None:
            start_wall = datetime.fromtimestamp(base_ts + float(group["start_sec"]))
            end_wall = datetime.fromtimestamp(base_ts + float(group["end_sec"]))
            from_s = start_wall.strftime("%Y-%m-%d %H:%M:%S")
            to_s = end_wall.strftime("%Y-%m-%d %H:%M:%S")
        else:
            from_s = base
            to_s = base

        inc_id, is_new = self.inc_db.merge_or_add_incident(
            timestamp=from_s,
            host=host,
            source="video",
            detection_type=alert["detection_type"],
            alert_level=alert["alert_level"],
            confidence=group["best_confidence"],
            description=desc,
            thumbnail_path=thumb,
            screenshot_path=screen,
            video_source=video_path,
            video_timestamp_sec=group["start_sec"],
            raw_text=alert.get("description", ""),
        )
        if not is_new:
            self.inc_db.extend_incident(
                inc_id,
                event_time=to_s,
                confidence=group["best_confidence"],
                description=desc,
                thumbnail_path=thumb,
                screenshot_path=screen,
            )
        else:
            self.inc_db.extend_incident(inc_id, event_time=to_s)

        alert["incident_id"] = inc_id
        alert["source"] = "video"
        alert["host"] = host
        alert["file_name"] = Path(video_path).name
        alert["merged"] = not is_new
        return alert

    def _kind_enabled(self, alert: dict) -> bool:
        """Keep alert only if its kind(s) are enabled in Settings."""
        has_nsfw = bool(alert.get("has_nsfw"))
        has_korea = bool(alert.get("has_korea"))
        kind = alert.get("alert_level", "")
        dtype = alert.get("detection_type") or ""
        if not has_nsfw and not has_korea:
            has_nsfw = kind in ("nsfw", "nsfw+korea") or "nsfw" in dtype
            has_korea = kind in ("korea", "nsfw+korea") or "korea" in dtype

        if has_nsfw and has_korea:
            return self.config.alert_nsfw or self.config.alert_korea
        if has_nsfw:
            return self.config.alert_nsfw
        if has_korea:
            return self.config.alert_korea
        return False

    def _scan_new_recordings(self) -> tuple[int, list[dict]]:
        """Scan newly appeared recording files with limits (images first).

        Returns (new_file_count_seen, incidents).
        """
        new_files = self.recording_watcher.get_new_files(
            images_first=self.config.media_scan_images_first
        )
        if not new_files:
            return 0, []

        sample_interval = self.config.sample_interval
        images_all = [f for f in new_files if f["type"] == "image"]
        # Copy state so we only commit timestamps for images we actually scan
        sample_state = dict(self._last_image_sample_ts)
        images_sampled = subsample_images_by_time(
            images_all,
            sample_interval,
            last_kept_ts=sample_state,
        )
        # Sample-rate skips are intentional — mark those seen so they are not retried
        sampled_paths = {f["path"] for f in images_sampled}
        skipped_sample = [f["path"] for f in images_all if f["path"] not in sampled_paths]
        if skipped_sample:
            self.recording_watcher.mark_seen(skipped_sample)

        images = images_sampled[: self.config.max_new_images_per_poll]
        deferred_images = images_sampled[self.config.max_new_images_per_poll :]
        n_video_new = len([f for f in new_files if f["type"] == "video"])
        if self.config.include_video:
            videos_all = [f for f in new_files if f["type"] == "video"]
            videos = videos_all[: self.config.max_new_videos_per_poll]
            deferred_videos_list = videos_all[self.config.max_new_videos_per_poll :]
        else:
            videos = []
            deferred_videos_list = []
            # Video off: never scan these; mark seen so they do not clog the queue
            if n_video_new:
                self.recording_watcher.mark_seen(
                    [f["path"] for f in new_files if f["type"] == "video"]
                )
                logger.info(
                    f"New recording(s): {n_video_new} video skipped (Include video off)"
                )
        to_scan = images + videos

        if to_scan:
            logger.info(
                f"New recording(s): {len(to_scan)} to scan "
                f"({len(images)}/{len(images_all)} image @ {sample_interval}s, "
                f"{len(videos)} video)"
            )
            if deferred_images or deferred_videos_list:
                logger.info(
                    f"  (plus {len(deferred_images)} image / "
                    f"{len(deferred_videos_list)} video deferred to next poll)"
                )

        incidents = []
        scanned_paths: list[str] = []
        for f in to_scan:
            label = self._recording_label(f)
            logger.info(f"New recording | {label}")
            scanned_paths.append(f["path"])
            if f["type"] == "image":
                inc = self.scan_screenshot(f["path"], host=f.get("host_hint", ""))
                found = [inc] if inc else []
            else:
                found = self.scan_video(f["path"], host=f.get("host_hint", ""))
            if found:
                for inc in found:
                    kind = (inc.get("alert_level") or "?").upper()
                    desc = self._clip(inc.get("description", "") or "", 80)
                    logger.info(f"  Detected {kind} — {desc}")
                incidents.extend(found)
            else:
                logger.info("  Detected: none (no NSFW / Korea)")

        # Mark scanned files seen; leave poll-limit deferrals unseen for next poll
        if scanned_paths:
            self.recording_watcher.mark_seen(scanned_paths)

        # Commit sample cursor from images actually scanned this poll
        if images:
            commit = dict(self._last_image_sample_ts)
            for e in images:
                host = (e.get("host_hint") or "") or "_"
                ts = parse_event_time(parse_recording_event_time(e.get("path") or ""))
                if ts is not None:
                    commit[host] = float(ts)
            self._last_image_sample_ts = commit

        return len(new_files), incidents

    @staticmethod
    def _recording_label(entry: dict) -> str:
        path = Path(entry.get("path") or "")
        kind = entry.get("type") or "file"
        host = entry.get("host_hint") or path.parent.name
        return f"{kind} | {host} | {path.name}"

    def _scan_history_media(self, start: str, end: str) -> list[dict]:
        """Scan recording folder media within a date range (sampled images; videos if on)."""
        files = self.recording_watcher.scan_all(
            images_first=self.config.media_scan_images_first
        )
        files = self.recording_watcher.filter_by_mtime_range(files, start, end)
        sample_interval = self.config.sample_interval
        images_all = [f for f in files if f["type"] == "image"]
        images = subsample_images_by_time(images_all, sample_interval)
        videos = (
            [f for f in files if f["type"] == "video"]
            if self.config.include_video
            else []
        )

        logger.info(
            f"History media: {len(images)}/{len(images_all)} image(s) "
            f"@ {sample_interval}s, {len(videos)} video(s)"
            f"{'' if self.config.include_video else ' (video off)'}"
        )

        incidents = []
        for i, f in enumerate(images, 1):
            if self.is_cancelled():
                break
            logger.info(f"History image {i}/{len(images)}: {Path(f['path']).name}")
            inc = self.scan_screenshot(f["path"], host=f.get("host_hint", ""))
            if inc:
                incidents.append(inc)

        for i, f in enumerate(videos, 1):
            if self.is_cancelled():
                break
            logger.info(f"History video {i}/{len(videos)}: {Path(f['path']).name}")
            incidents += self.scan_video(f["path"], host=f.get("host_hint", ""))

        return incidents

    # Max detail lines per poll for Status Log (avoids flood)
    _NEW_DATA_LOG_CAP = 40

    @staticmethod
    def _clip(text: str, n: int = 100) -> str:
        text = (text or "").replace("\n", " ").strip()
        if len(text) <= n:
            return text
        return text[: n - 1] + "…"

    def _log_new_data_rows(self, kind: str, rows: list[dict]) -> None:
        """List new Net Monitor rows in Status Log with useful content."""
        if not rows:
            return
        logger.info(f"New {kind}: {len(rows)} row(s)")
        cap = self._NEW_DATA_LOG_CAP
        for i, row in enumerate(rows):
            if i >= cap:
                logger.info(f"  … and {len(rows) - cap} more {kind}")
                break
            logger.info(f"  {self._format_new_row(kind, row)}")

    def _format_new_row(self, kind: str, row: dict) -> str:
        host = self._clip(row.get("HOST", "") or "", 40)
        t = self._clip(row.get("TIME", "") or "", 19)
        if kind == "weblog":
            title = self._clip(row.get("TITLE", "") or "", 60)
            url = self._clip(row.get("URL", "") or "", 120)
            parts = [p for p in (t, host, title, url) if p]
            return "weblog | " + " | ".join(parts)
        if kind == "applog":
            binary = row.get("BINARY", "") or ""
            app = Path(binary).name if binary else ""
            caption = self._clip(row.get("CAPTION", "") or "", 80)
            parts = [p for p in (t, host, app, caption) if p]
            return "applog | " + " | ".join(parts)
        # keylog — caption only (keystrokes not scanned by default)
        caption = self._clip(row.get("CAPTION", "") or "", 100)
        parts = [p for p in (t, host, caption) if p]
        return "keylog | " + " | ".join(parts)

    def _scan_weblogs(self, since: Optional[str]) -> tuple[int, list[dict]]:
        rows = self.nm_db.get_weblogs(since=since)
        self._log_new_data_rows("weblog", rows)
        incidents = []
        last_time = since
        for row in rows:
            inc = self._process_weblog(row)
            if inc:
                incidents.append(inc)
            last_time = row.get("TIME", last_time)
        if last_time and last_time != since:
            self.inc_db.update_scan_state(last_weblog_time=last_time)
        return len(rows), incidents

    def _scan_applogs(self, since: Optional[str]) -> tuple[int, list[dict]]:
        rows = self.nm_db.get_applogs(since=since)
        self._log_new_data_rows("applog", rows)
        incidents = []
        last_time = since
        for row in rows:
            inc = self._process_applog(row)
            if inc:
                incidents.append(inc)
            last_time = row.get("TIME", last_time)
        if last_time and last_time != since:
            self.inc_db.update_scan_state(last_applog_time=last_time)
        return len(rows), incidents

    def _scan_keylogs(self, since: Optional[str]) -> tuple[int, list[dict]]:
        rows = self.nm_db.get_keylogs(since=since)
        self._log_new_data_rows("keylog", rows)
        incidents = []
        last_time = since
        for row in rows:
            inc = self._process_keylog(row)
            if inc:
                incidents.append(inc)
            last_time = row.get("TIME", last_time)
        if last_time and last_time != since:
            self.inc_db.update_scan_state(last_keylog_time=last_time)
        return len(rows), incidents

    def _should_save_alert(
        self,
        alert: dict,
        host: str,
        event_time: str,
        url: str = "",
        app_name: str = "",
    ) -> bool:
        """Save every NSFW/Korea hit — no dedupe."""
        return self._kind_enabled(alert)

    def _record_watched_from_url(
        self,
        url: str,
        host: str,
        event_time: str,
        user: str = "",
    ):
        hit = self.domain_app_detector.detect_watched_website(url)
        if not hit or not self.visit_store or not self._record_visits:
            return
        matched = hit.get("matched") or ""
        self.visit_store.record_visit(
            timestamp=event_time,
            host=host,
            source=source_label(matched, "website"),
            kind="website",
            matched=matched,
            url=url,
            user=user,
        )
        logger.info(
            "Watched visit | website | %s | %s | %s",
            host or "—",
            matched,
            self._clip(url, 120),
        )

    def _record_watched_from_app(
        self,
        binary: str,
        host: str,
        event_time: str,
        user: str = "",
    ):
        hit = self.domain_app_detector.detect_watched_app(binary)
        if not hit or not self.visit_store or not self._record_visits:
            return
        matched = hit.get("matched") or ""
        app = Path(binary).name if binary else matched
        self.visit_store.record_visit(
            timestamp=event_time,
            host=host,
            source=source_label(matched, "app"),
            kind="app",
            matched=matched,
            app_name=binary,
            user=user,
        )
        logger.info(
            "Watched visit | app | %s | %s | %s",
            host or "—",
            matched,
            self._clip(app, 80),
        )

    def _evidence_image(self, row: dict, host: str, event_time: str) -> Optional[str]:
        """Prefer Net Monitor SCREENSHOT; else nearest recording JPG for host/time."""
        screenshot = (row.get("SCREENSHOT") or "").strip()
        if screenshot and Path(screenshot).exists():
            return screenshot
        rec = self._history_folder or self.config.recording_path
        return find_nearest_screen_image(rec, host, event_time)

    def _attach_images(self, source_image: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """Copy evidence into AutoLook thumbnails/screenshots folders.

        Survives Net Monitor deleting/moving originals. Returns
        (thumbnail_path, screenshot_path).
        """
        if not source_image or not Path(source_image).exists():
            return None, None
        thumb, screen = save_incident_images(
            source_image,
            self.config.thumbnail_path,
            self.config.screenshot_path,
        )
        if thumb or screen:
            return thumb, screen or thumb
        # Fallback if copy fails — still keep a usable path in the alert
        return str(source_image), str(source_image)

    def _process_weblog(self, row: dict) -> Optional[dict]:
        url = row.get("URL", "") or ""
        title = row.get("TITLE", "") or ""
        combined_text = f"{title} {url}"
        host = row.get("HOST", "") or ""
        event_time = row.get("TIME", "") or ""
        user = row.get("USER", "") or ""

        self._record_watched_from_url(url, host, event_time, user=user)

        detections = []
        detections += self.text_detector.detect_all(combined_text)
        detections += self.domain_app_detector.detect_all_url(url)

        if is_google_translate_context(url, title):
            detections = strip_korea_detections(detections)

        evidence = self._evidence_image(row, host, event_time)
        if evidence:
            nsfw = self.nsfw_detector.detect_file(evidence)
            if nsfw:
                detections.append(nsfw)

        alert = self.alert_scorer.score(detections)
        if not alert:
            return None
        if not self._should_save_alert(alert, host, event_time, url=url):
            return None

        thumb, screen = self._attach_images(evidence)

        inc_id, is_new = self.inc_db.merge_or_add_incident(
            timestamp=event_time,
            host=host,
            user=row.get("USER", ""),
            source="weblog",
            detection_type=alert["detection_type"],
            alert_level=alert["alert_level"],
            confidence=alert.get("confidence"),
            description=alert["description"],
            url=url,
            thumbnail_path=thumb,
            screenshot_path=screen,
            raw_text=combined_text[:500],
        )
        alert["incident_id"] = inc_id
        alert["source"] = "weblog"
        alert["host"] = host
        alert["url"] = url
        alert["title"] = title
        alert["row"] = row
        alert["merged"] = not is_new
        return alert

    def _process_applog(self, row: dict) -> Optional[dict]:
        binary = row.get("BINARY", "") or ""
        caption = row.get("CAPTION", "") or ""
        descr = row.get("DESCR", "") or ""
        combined_text = f"{caption} {descr}"
        host = row.get("HOST", "") or ""
        event_time = row.get("TIME", "") or ""
        user = row.get("USER", "") or ""

        self._record_watched_from_app(binary, host, event_time, user=user)

        detections = []
        detections += self.text_detector.detect_all(combined_text)
        detections += self.domain_app_detector.detect_all_app(binary)

        if is_google_translate_context(caption, descr, binary):
            detections = strip_korea_detections(detections)

        evidence = self._evidence_image(row, host, event_time)
        if evidence:
            nsfw = self.nsfw_detector.detect_file(evidence)
            if nsfw:
                detections.append(nsfw)

        alert = self.alert_scorer.score(detections)
        if not alert:
            return None
        if not self._should_save_alert(alert, host, event_time, app_name=binary):
            return None

        thumb, screen = self._attach_images(evidence)

        inc_id, is_new = self.inc_db.merge_or_add_incident(
            timestamp=event_time,
            host=host,
            user=row.get("USER", ""),
            source="applog",
            detection_type=alert["detection_type"],
            alert_level=alert["alert_level"],
            confidence=alert.get("confidence"),
            description=alert["description"],
            app_name=binary,
            thumbnail_path=thumb,
            screenshot_path=screen,
            raw_text=combined_text[:500],
        )
        alert["incident_id"] = inc_id
        alert["source"] = "applog"
        alert["host"] = host
        alert["app_name"] = Path(binary).name if binary else binary
        alert["caption"] = caption
        alert["row"] = row
        alert["merged"] = not is_new
        return alert

    def _process_keylog(self, row: dict) -> Optional[dict]:
        caption = row.get("CAPTION", "") or ""
        host = row.get("HOST", "") or ""
        event_time = row.get("TIME", "") or ""
        # Typing Korean is allowed by default — only scan caption (window title).
        text = caption
        if not self.config.skip_keylog_keystrokes:
            ks = row.get("KEYSTROKES", "") or ""
            if ks:
                text = f"{caption} {ks}".strip()
        detections = self.text_detector.detect_all(text)
        if is_google_translate_context(caption, text):
            detections = strip_korea_detections(detections)

        alert = self.alert_scorer.score(detections)
        if not alert:
            return None
        if not self._should_save_alert(alert, host, event_time):
            return None

        evidence = self._evidence_image(row, host, event_time)
        thumb, screen = self._attach_images(evidence)

        inc_id, is_new = self.inc_db.merge_or_add_incident(
            timestamp=event_time,
            host=host,
            user=row.get("USER", ""),
            source="keylog_caption",
            detection_type=alert["detection_type"],
            alert_level=alert["alert_level"],
            confidence=alert.get("confidence"),
            description=alert["description"],
            thumbnail_path=thumb,
            screenshot_path=screen,
            raw_text=text[:500],
        )
        alert["incident_id"] = inc_id
        alert["source"] = "keylog_caption"
        alert["host"] = host
        alert["caption"] = caption
        alert["row"] = row
        alert["merged"] = not is_new
        return alert
