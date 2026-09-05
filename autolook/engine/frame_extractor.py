"""Extract frames from video files using FFmpeg (PATH or imageio-ffmpeg)."""

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_FFMPEG_CACHE: str | None = None


def _find_ffmpeg() -> str:
    """Find ffmpeg executable (system PATH or bundled imageio-ffmpeg)."""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE:
        return _FFMPEG_CACHE

    for candidate in ("ffmpeg", "ffmpeg.exe"):
        path = shutil.which(candidate)
        if path:
            _FFMPEG_CACHE = path
            return path

    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            _FFMPEG_CACHE = path
            logger.info(f"Using bundled ffmpeg: {path}")
            return path
    except Exception as e:
        logger.debug(f"imageio-ffmpeg not available: {e}")

    raise FileNotFoundError(
        "ffmpeg not found. Install imageio-ffmpeg (`pip install imageio-ffmpeg`) "
        "or add ffmpeg to PATH."
    )


def get_video_duration(video_path: str | Path) -> float:
    """Get video duration in seconds using ffmpeg -i parse (works without ffprobe)."""
    ffmpeg = _find_ffmpeg()
    try:
        result = subprocess.run(
            [ffmpeg, "-i", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        # Duration is in stderr: Duration: 00:01:23.45
        import re
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
        if m:
            h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mn * 60 + s
    except Exception as e:
        logger.error(f"Cannot get video duration: {e}")
    return 0.0


def extract_frames(
    video_path: str | Path,
    interval_seconds: int = 3,
    output_dir: Path | None = None,
    max_frames: int = 200,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict]:
    """Extract frames from video at given interval.

    max_frames <= 0 means no cap (full video at the sample interval).
    cancel_check: optional callable; when True, kills ffmpeg and returns
    whatever frames were written so far.

    Returns list of dicts: {path, timestamp_sec, index}
    """
    ffmpeg = _find_ffmpeg()
    video_path = Path(video_path)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="autolook_frames_"))
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    duration = get_video_duration(video_path)
    interval = max(interval_seconds, 1)
    if duration <= 0:
        if max_frames <= 0:
            max_frames = 200
        duration = max_frames * interval
        logger.warning(
            f"Unknown duration for {video_path.name}, capping at {max_frames} frames"
        )

    if max_frames <= 0:
        frame_limit = max(1, int(duration / interval) + 2)
        logger.info(
            f"Extracting ALL frames from {video_path.name} "
            f"(~{duration:.0f}s, every {interval}s → up to {frame_limit})"
        )
    else:
        frame_limit = min(int(duration / interval) + 1, max_frames)
        logger.info(
            f"Extracting up to {frame_limit} frames from {video_path.name} (~{duration:.0f}s)"
        )

    output_pattern = str(output_dir / "frame_%06d.jpg")
    timeout = max(300, int(duration) * 2 + 120)
    cancelled = False

    try:
        proc = subprocess.Popen(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-i", str(video_path),
                "-vf", f"fps=1/{interval}",
                "-q:v", "3",
                "-frames:v", str(frame_limit),
                "-y", output_pattern,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if cancel_check and cancel_check():
                cancelled = True
                logger.info(f"Stopping frame extract for {video_path.name}")
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                break
            if time.monotonic() > deadline:
                logger.warning(f"FFmpeg timed out for {video_path}")
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                break
            time.sleep(0.2)
    except Exception as e:
        logger.error(f"FFmpeg error: {e}")
        return []

    frames = []
    for f in sorted(output_dir.glob("frame_*.jpg")):
        idx = int(f.stem.split("_")[1]) - 1
        ts = idx * interval
        frames.append({
            "path": str(f),
            "timestamp_sec": float(ts),
            "index": idx,
        })

    if cancelled:
        logger.info(
            f"Extract stopped early: {len(frames)} frame(s) from {video_path.name}"
        )
    else:
        logger.info(f"Extracted {len(frames)} frames from {video_path.name}")
    return frames


def extract_single_frame(video_path: str | Path, timestamp_sec: float, output_path: str | Path) -> bool:
    """Extract a single frame at a specific timestamp."""
    ffmpeg = _find_ffmpeg()
    try:
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-ss", str(timestamp_sec),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                "-y", str(output_path),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return Path(output_path).exists()
    except Exception as e:
        logger.error(f"Single frame extraction error: {e}")
        return False
