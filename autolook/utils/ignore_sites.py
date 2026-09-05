"""Ignore contexts that produce false Korea alerts (e.g. Google Translate)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Domains / host patterns for Google Translate
_TRANSLATE_HOST_RE = re.compile(
    r"(^|\.)translate\.google\."  # translate.google.com, .co.kr, .co.uk, ...
    r"|translate\.googleapis\."
    r"|translate\.googleusercontent\.",
    re.IGNORECASE,
)

# URL path / query markers
_TRANSLATE_URL_MARKERS = (
    "translate.google.",
    "google.com/translate",
    "google.co.kr/translate",
    "&tl=ko",
    "?tl=ko",
    "&sl=ko",
    "?sl=ko",
    "client=te",  # translate extension client
)

# Visible UI / title / OCR text markers
_TRANSLATE_TEXT_MARKERS = (
    "google translate",
    "translate.google",
    "번역 - google",
    "google 번역",
    "google translate -",
    "detected language",
    "detection language",
    # Common OCR misreads of "Google Translate"
    "fuogle",
    "tralslal",
    "translai",
    "googl translate",
    "google tr",
)


def _hostname(url: str) -> str:
    if not url:
        return ""
    text = url.strip()
    if not text.startswith(("http://", "https://")):
        text = "http://" + text
    try:
        return (urlparse(text).hostname or "").lower()
    except Exception:
        return ""


def is_google_translate_context(*parts: str) -> bool:
    """True if URL, title, caption, or OCR text looks like Google Translate."""
    blob = " ".join(p for p in parts if p).lower()
    if not blob.strip():
        return False

    host = _hostname(blob if "://" in blob or blob.startswith("translate.") else "")
    # Also try each part as a possible URL
    for p in parts:
        if not p:
            continue
        h = _hostname(p)
        if h and _TRANSLATE_HOST_RE.search(h):
            return True
        pl = p.lower()
        if any(m in pl for m in _TRANSLATE_URL_MARKERS):
            return True

    if _TRANSLATE_HOST_RE.search(blob):
        return True
    if any(m in blob for m in _TRANSLATE_TEXT_MARKERS):
        return True
    return False


# On Google Translate, Hangul on-screen is expected (translation UI) — ignore it.
# English/custom keywords (korea, seoul, …) must still alert.
_TRANSLATE_IGNORE_TYPES = {"hangul", "korean_domain"}


def strip_korea_detections(detections: list[dict]) -> list[dict]:
    """For Google Translate context: drop Hangul / .kr domain FPs.

    Keeps english_keyword and custom_keyword so keyword detection still runs.
    Also keeps NSFW and other non-Korea signals.
    """
    return [d for d in detections if d.get("type") not in _TRANSLATE_IGNORE_TYPES]


def strip_hangul_only(detections: list[dict]) -> list[dict]:
    """Alias — same as strip_korea_detections (keywords preserved)."""
    return strip_korea_detections(detections)
