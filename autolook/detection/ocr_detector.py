"""Korean + English OCR detection using EasyOCR (offline)."""

import logging
import re
from pathlib import Path

from autolook.utils.hangul import HANGUL_PATTERN, extract_hangul
from autolook.utils.ignore_sites import is_google_translate_context

logger = logging.getLogger(__name__)

# EasyOCR often invents Hangul from blurry English on wide screenshots.
# Only keep Hangul boxes that clear this confidence bar.
MIN_HANGUL_BOX_CONF = 0.55
# Need enough real Hangul signal (not 1–2 garbage syllables)
MIN_HANGUL_CHARS = 4
MIN_HANGUL_BOXES = 2

_reader = None


def _load_reader():
    """Lazy-load EasyOCR reader with Korean + English."""
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
            logger.info("EasyOCR reader loaded (Korean + English, CPU).")
        except ImportError:
            logger.warning("easyocr not installed. OCR detection disabled.")
            _reader = False
    return _reader if _reader is not False else None


def _hangul_in(text: str) -> str:
    return "".join(HANGUL_PATTERN.findall(text or ""))


class OCRDetector:
    """Extract text from images via OCR and detect Korean content."""

    def __init__(
        self,
        english_keywords: list[str],
        custom_keywords: list[str],
        min_hangul_conf: float = MIN_HANGUL_BOX_CONF,
    ):
        self._english_keywords = [kw.lower() for kw in english_keywords if kw]
        self._custom_keywords = [kw.lower() for kw in custom_keywords if kw]
        self._min_hangul_conf = min_hangul_conf
        self._english_patterns = [
            re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            for kw in self._english_keywords
        ]
        self._custom_patterns = [
            re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            for kw in self._custom_keywords
        ]

    def detect_file(self, image_path: str | Path) -> list[dict]:
        """Run OCR on an image file and return detection results."""
        reader = _load_reader()
        if reader is None:
            return []

        try:
            results = reader.readtext(str(image_path), detail=1)
        except Exception as e:
            logger.error(f"OCR error on {image_path}: {e}")
            return []

        full_text = " ".join(r[1] for r in results if r[1])
        if not full_text.strip():
            return []

        # Google Translate chrome / UI — ignore Korea signal
        if is_google_translate_context(full_text):
            logger.debug(f"OCR ignored (Google Translate): {image_path}")
            return self._analyze_english_only(full_text)

        return self._analyze_text(full_text, results)

    def detect_text(self, ocr_text: str) -> list[dict]:
        """Analyze already-extracted OCR text for Korean/keyword content."""
        if not ocr_text or not ocr_text.strip():
            return []
        if is_google_translate_context(ocr_text):
            return self._analyze_english_only(ocr_text)
        return self._analyze_text(ocr_text, [])

    def _analyze_english_only(self, full_text: str) -> list[dict]:
        """Keyword checks without Hangul (Translate / ignored pages)."""
        return self._keyword_detections(full_text)

    def _confident_hangul(self, raw_results: list) -> tuple[list[str], float, int]:
        """Collect Hangul only from high-confidence OCR boxes."""
        words: list[str] = []
        confs: list[float] = []
        hangul_boxes = 0

        for item in raw_results:
            if len(item) < 3:
                continue
            text = item[1] or ""
            try:
                conf = float(item[2])
            except (TypeError, ValueError):
                conf = 0.0
            if conf < self._min_hangul_conf:
                continue
            h = _hangul_in(text)
            if len(h) < 2:
                continue
            hangul_boxes += 1
            words.extend(extract_hangul(text) or ([h] if len(h) >= 2 else []))
            confs.append(conf)

        avg = sum(confs) / len(confs) if confs else 0.0
        seen: set[str] = set()
        uniq: list[str] = []
        for w in words:
            if w not in seen:
                seen.add(w)
                uniq.append(w)
        return uniq, avg, hangul_boxes

    def _analyze_text(self, full_text: str, raw_results: list) -> list[dict]:
        detections = []

        if raw_results:
            hangul_words, avg_conf, box_count = self._confident_hangul(raw_results)
            total_chars = sum(len(w) for w in hangul_words)
            strong = (
                box_count >= MIN_HANGUL_BOXES and total_chars >= MIN_HANGUL_CHARS
            ) or (total_chars >= 8 and avg_conf >= self._min_hangul_conf)
            if strong and hangul_words:
                detections.append({
                    "type": "hangul",
                    "matched": hangul_words[:10],
                    "text": full_text[:300],
                    "source": "ocr",
                    "confidence": avg_conf,
                })
        else:
            # Text-only path (no per-box conf) — require more Hangul chars
            hangul_words = extract_hangul(full_text)
            total_chars = sum(len(w) for w in hangul_words)
            if hangul_words and total_chars >= MIN_HANGUL_CHARS:
                detections.append({
                    "type": "hangul",
                    "matched": hangul_words[:10],
                    "text": full_text[:300],
                    "source": "ocr",
                })

        detections.extend(self._keyword_detections(full_text))
        return detections

    def _keyword_detections(self, full_text: str) -> list[dict]:
        detections = []
        matched_english = []
        for pattern, kw in zip(self._english_patterns, self._english_keywords):
            if pattern.search(full_text):
                matched_english.append(kw)
        if matched_english:
            detections.append({
                "type": "english_keyword",
                "matched": matched_english,
                "text": full_text[:300],
                "source": "ocr",
            })

        matched_custom = []
        for pattern, kw in zip(self._custom_patterns, self._custom_keywords):
            if pattern.search(full_text):
                matched_custom.append(kw)
        if matched_custom:
            detections.append({
                "type": "custom_keyword",
                "matched": matched_custom,
                "text": full_text[:300],
                "source": "ocr",
            })
        return detections
