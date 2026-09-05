"""Save screen images and thumbnails for incidents."""

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None
    ImageFilter = None


def _unique_name(prefix: str = "", ext: str = ".jpg") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}{stamp}_{uuid.uuid4().hex[:8]}{ext}"


def save_screen_image(
    image_path: str | Path,
    output_dir: Path,
    max_width: int = 1920,
    quality: int = 90,
) -> Optional[str]:
    """Save a clear screen copy (full or lightly resized). Returns saved path."""
    if Image is None:
        return None
    try:
        src = Path(image_path)
        if not src.exists():
            return None
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / _unique_name("screen_")

        img = Image.open(src)
        # Keep readable size — only shrink if wider than max_width
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, max(1, int(img.height * ratio)))
            img = img.resize(new_size, Image.LANCZOS)
        img.convert("RGB").save(str(out_path), "JPEG", quality=quality)
        return str(out_path)
    except Exception:
        # Fallback: raw copy
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / _unique_name("screen_", src.suffix or ".jpg")
            shutil.copy2(src, out_path)
            return str(out_path)
        except Exception:
            return None


def save_thumbnail(
    image_path: str | Path,
    output_dir: Path,
    max_size: tuple[int, int] = (960, 540),
    blur: bool = False,
) -> Optional[str]:
    """Save a preview thumbnail (large enough to read UI text)."""
    if Image is None:
        return None
    try:
        img = Image.open(image_path)
        img.thumbnail(max_size, Image.LANCZOS)
        if blur and ImageFilter is not None:
            img = img.filter(ImageFilter.GaussianBlur(radius=15))
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / _unique_name("thumb_")
        img.convert("RGB").save(str(out_path), "JPEG", quality=85)
        return str(out_path)
    except Exception:
        return None


def save_frame_as_thumbnail(
    frame_data: bytes,
    output_dir: Path,
    max_size: tuple[int, int] = (960, 540),
    blur: bool = False,
) -> Optional[str]:
    """Save raw image bytes as a thumbnail."""
    if Image is None:
        return None
    try:
        import io
        img = Image.open(io.BytesIO(frame_data))
        img.thumbnail(max_size, Image.LANCZOS)
        if blur and ImageFilter is not None:
            img = img.filter(ImageFilter.GaussianBlur(radius=15))
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / _unique_name("thumb_")
        img.convert("RGB").save(str(out_path), "JPEG", quality=85)
        return str(out_path)
    except Exception:
        return None


def save_incident_images(
    image_path: str | Path,
    thumbnail_dir: Path,
    screenshot_dir: Path,
) -> tuple[Optional[str], Optional[str]]:
    """Save both a clear screen image and a list thumbnail.

    Returns (thumbnail_path, screenshot_path).
    """
    screen = save_screen_image(image_path, screenshot_dir)
    # Prefer building thumb from full screen copy; fall back to source
    thumb_src = screen or str(image_path)
    thumb = save_thumbnail(thumb_src, thumbnail_dir)
    return thumb, screen
