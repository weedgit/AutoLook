"""Text-based detection: Hangul, English keywords, custom keywords."""

import re
from typing import Optional

from autolook.utils.hangul import contains_hangul, contains_hangul_word, extract_hangul


class TextDetector:
    """Detects Korean text, English keywords, and custom keywords in strings."""

    def __init__(
        self,
        english_keywords: list[str],
        custom_keywords: list[str],
    ):
        self._english_patterns = [
            re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            for kw in english_keywords
            if kw
        ]
        self._english_keywords = [kw.lower() for kw in english_keywords if kw]
        self._custom_patterns = [
            re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            for kw in custom_keywords
            if kw
        ]
        self._custom_keywords = [kw.lower() for kw in custom_keywords if kw]

    def detect_hangul(self, text: str) -> Optional[dict]:
        """Check for Hangul characters in text."""
        if not text:
            return None
        if contains_hangul_word(text):
            words = extract_hangul(text)
            return {
                "type": "hangul",
                "matched": words[:10],
                "text": text[:200],
            }
        return None

    def detect_english_keywords(self, text: str) -> Optional[dict]:
        """Check for English Korea-related keywords."""
        if not text:
            return None
        matched = []
        for pattern, kw in zip(self._english_patterns, self._english_keywords):
            if pattern.search(text):
                matched.append(kw)
        if matched:
            return {
                "type": "english_keyword",
                "matched": matched,
                "text": text[:200],
            }
        return None

    def detect_custom_keywords(self, text: str) -> Optional[dict]:
        """Check for admin-defined custom keywords."""
        if not text:
            return None
        matched = []
        for pattern, kw in zip(self._custom_patterns, self._custom_keywords):
            if pattern.search(text):
                matched.append(kw)
        if matched:
            return {
                "type": "custom_keyword",
                "matched": matched,
                "text": text[:200],
            }
        return None

    def detect_all(self, text: str) -> list[dict]:
        """Run all text detectors and return list of findings."""
        results = []
        r = self.detect_hangul(text)
        if r:
            results.append(r)
        r = self.detect_english_keywords(text)
        if r:
            results.append(r)
        r = self.detect_custom_keywords(text)
        if r:
            results.append(r)
        return results
