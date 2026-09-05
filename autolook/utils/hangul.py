"""Hangul (Korean) character detection utilities."""

import re

# Unicode ranges for Korean characters
_HANGUL_SYLLABLES = (0xAC00, 0xD7AF)      # 가 – 힣
_HANGUL_JAMO = (0x1100, 0x11FF)            # ᄀ – ᇿ
_HANGUL_COMPAT_JAMO = (0x3130, 0x318F)     # ㄱ – ㅣ
_HANGUL_JAMO_EXT_A = (0xA960, 0xA97F)
_HANGUL_JAMO_EXT_B = (0xD7B0, 0xD7FF)

# Regex pattern matching any Hangul character
HANGUL_PATTERN = re.compile(
    r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F\uA960-\uA97F\uD7B0-\uD7FF]"
)

# Matches a sequence of 2+ Hangul characters (reduces false positives from single chars)
HANGUL_WORD_PATTERN = re.compile(
    r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F\uA960-\uA97F\uD7B0-\uD7FF]{2,}"
)


def contains_hangul(text: str) -> bool:
    """Return True if text contains any Hangul character."""
    if not text:
        return False
    return bool(HANGUL_PATTERN.search(text))


def contains_hangul_word(text: str) -> bool:
    """Return True if text contains 2+ consecutive Hangul characters."""
    if not text:
        return False
    return bool(HANGUL_WORD_PATTERN.search(text))


def extract_hangul(text: str) -> list[str]:
    """Extract all Hangul word sequences from text."""
    if not text:
        return []
    return HANGUL_WORD_PATTERN.findall(text)


def hangul_ratio(text: str) -> float:
    """Return the ratio of Hangul characters to total characters."""
    if not text:
        return 0.0
    hangul_count = len(HANGUL_PATTERN.findall(text))
    return hangul_count / len(text)
