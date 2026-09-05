"""Watched website and application detection."""

import fnmatch
import re
from typing import Optional
from urllib.parse import urlparse


class DomainAppDetector:
    """Matches URLs against watched websites and process names against watched apps."""

    def __init__(
        self,
        watched_websites: list[str],
        watched_apps: list[str],
        korean_domains: list[str],
    ):
        self._watched_websites = [w.lower() for w in watched_websites]
        self._watched_apps = [a.lower() for a in watched_apps]
        self._korean_domains = [d.lower() for d in korean_domains]

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL, handling common cases."""
        if not url:
            return ""
        url_lower = url.lower().strip()
        if not url_lower.startswith(("http://", "https://")):
            url_lower = "http://" + url_lower
        try:
            parsed = urlparse(url_lower)
            return parsed.hostname or ""
        except Exception:
            return ""

    def _domain_matches(self, domain: str, pattern: str) -> bool:
        """Check if domain matches a pattern (supports *.kr style wildcards)."""
        if not domain or not pattern:
            return False
        if pattern.startswith("*."):
            suffix = pattern[1:]
            return domain.endswith(suffix) or domain == pattern[2:]
        return domain == pattern or domain.endswith("." + pattern)

    def detect_watched_website(self, url: str) -> Optional[dict]:
        """Check if URL belongs to a watched website."""
        domain = self._extract_domain(url)
        if not domain:
            return None
        for site in self._watched_websites:
            if self._domain_matches(domain, site):
                return {
                    "type": "watched_site",
                    "matched": site,
                    "domain": domain,
                    "url": url[:300],
                }
        return None

    def detect_korean_domain(self, url: str) -> Optional[dict]:
        """Check if URL belongs to a Korean domain."""
        domain = self._extract_domain(url)
        if not domain:
            return None
        for pattern in self._korean_domains:
            if self._domain_matches(domain, pattern):
                return {
                    "type": "korean_domain",
                    "matched": pattern,
                    "domain": domain,
                    "url": url[:300],
                }
        return None

    def detect_watched_app(self, binary: str) -> Optional[dict]:
        """Check if a process/binary name matches watched apps."""
        if not binary:
            return None
        binary_lower = binary.lower().strip()
        # Handle full paths: extract just the filename
        if "\\" in binary_lower or "/" in binary_lower:
            binary_lower = binary_lower.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        for app in self._watched_apps:
            if binary_lower == app or binary_lower.startswith(app.replace(".exe", "")):
                return {
                    "type": "watched_app",
                    "matched": app,
                    "binary": binary[:200],
                }
        return None

    def detect_all_url(self, url: str) -> list[dict]:
        """Run all URL-based detectors."""
        results = []
        r = self.detect_watched_website(url)
        if r:
            results.append(r)
        r = self.detect_korean_domain(url)
        if r:
            results.append(r)
        return results

    def detect_all_app(self, binary: str) -> list[dict]:
        """Run all app-based detectors."""
        results = []
        r = self.detect_watched_app(binary)
        if r:
            results.append(r)
        return results
