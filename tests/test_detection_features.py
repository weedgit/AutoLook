"""Review tests: Hangul, keywords, Translate ignore, NSFW smoke, new-data cursor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from autolook.detection.alert_scorer import AlertScorer
from autolook.detection.domain_app_detector import DomainAppDetector
from autolook.detection.nsfw_detector import NSFWDetector, opennsfw_available
from autolook.detection.ocr_detector import OCRDetector
from autolook.detection.text_detector import TextDetector
from autolook.engine.watcher import RecordingWatcher
from autolook.utils.hangul import contains_hangul, contains_hangul_word, extract_hangul
from autolook.utils.ignore_sites import (
    is_google_translate_context,
    strip_korea_detections,
)


ENGLISH_KW = ["korean", "korea", "seoul", "hangul"]
CUSTOM_KW = ["secretcode", "특별단어"]


class TestHangul(unittest.TestCase):
    def test_hangul_word_requires_two_chars(self):
        self.assertTrue(contains_hangul("가"))
        self.assertFalse(contains_hangul_word("가"))
        self.assertTrue(contains_hangul_word("한국"))
        self.assertEqual(extract_hangul("Hello 안녕하세요 world"), ["안녕하세요"])

    def test_text_detector_hangul_without_translate(self):
        td = TextDetector(ENGLISH_KW, CUSTOM_KW)
        hits = td.detect_all("Window title: 한국어 뉴스")
        types = {h["type"] for h in hits}
        self.assertIn("hangul", types)
        self.assertNotIn("english_keyword", types)


class TestKeywords(unittest.TestCase):
    def setUp(self):
        self.td = TextDetector(ENGLISH_KW, CUSTOM_KW)

    def test_english_keywords(self):
        hits = self.td.detect_all("News from Seoul and Korea")
        eng = [h for h in hits if h["type"] == "english_keyword"][0]
        self.assertIn("seoul", eng["matched"])
        self.assertIn("korea", eng["matched"])

    def test_english_word_boundary(self):
        # "koreans" should not match "korea" as whole word... actually korea is prefix
        # \bkorea\b does not match koreans
        self.assertIsNone(self.td.detect_english_keywords("koreans abroad"))

    def test_custom_ascii_and_hangul(self):
        hits = self.td.detect_all("payload secretcode here")
        self.assertTrue(any(h["type"] == "custom_keyword" for h in hits))
        hits2 = self.td.detect_all("메모: 특별단어 포함")
        self.assertTrue(any(h["type"] == "custom_keyword" for h in hits2))


class TestTranslateIgnore(unittest.TestCase):
    def test_translate_url_detected(self):
        self.assertTrue(
            is_google_translate_context("https://translate.google.com/?sl=en&tl=ko")
        )
        self.assertTrue(is_google_translate_context("Google Translate - Korean"))
        self.assertFalse(is_google_translate_context("https://naver.com/news"))

    def test_strip_keeps_keywords_drops_hangul(self):
        dets = [
            {"type": "hangul", "matched": ["안녕"]},
            {"type": "english_keyword", "matched": ["korea"]},
            {"type": "korean_domain", "matched": "*.kr"},
            {"type": "nsfw", "confidence": 0.9},
            {"type": "custom_keyword", "matched": ["secretcode"]},
        ]
        kept = strip_korea_detections(dets)
        types = {d["type"] for d in kept}
        self.assertEqual(
            types, {"english_keyword", "nsfw", "custom_keyword"}
        )

    def test_weblog_like_pipeline(self):
        td = TextDetector(ENGLISH_KW, CUSTOM_KW)
        url = "https://translate.google.com/?tl=ko&text=hello"
        title = "Google Translate"
        dets = td.detect_all(f"{title} {url} 안녕하세요 korea")
        if is_google_translate_context(url, title):
            dets = strip_korea_detections(dets)
        types = {d["type"] for d in dets}
        self.assertNotIn("hangul", types)
        self.assertIn("english_keyword", types)


class TestKoreanDomainAndWatched(unittest.TestCase):
    def setUp(self):
        self.dd = DomainAppDetector(
            watched_websites=["youtube.com", "discord.com"],
            watched_apps=["discord.exe", "KakaoTalk.exe"],
            korean_domains=["naver.com", "daum.net", "*.kr"],
        )

    def test_korean_domains(self):
        self.assertEqual(
            self.dd.detect_korean_domain("https://www.naver.com/")["type"],
            "korean_domain",
        )
        # *.kr matches hosts ending in .kr
        self.assertEqual(
            self.dd.detect_korean_domain("https://www.example.kr/news")["matched"],
            "*.kr",
        )
        self.assertIsNone(self.dd.detect_korean_domain("https://news.chosun.com/"))
        self.assertIsNone(self.dd.detect_korean_domain("https://example.com/"))

    def test_watched_not_korea_alert(self):
        url_hits = self.dd.detect_all_url("https://www.youtube.com/watch?v=1")
        scorer = AlertScorer()
        # watched_site alone must not create NSFW/Korea alert
        self.assertIsNone(scorer.score(url_hits))
        # korean domain does
        kr = self.dd.detect_all_url("https://blog.naver.com/x")
        alert = scorer.score(kr)
        self.assertEqual(alert["alert_level"], "korea")


class TestAlertScorer(unittest.TestCase):
    def test_nsfw_korea_combo(self):
        scorer = AlertScorer()
        a = scorer.score(
            [
                {"type": "nsfw", "confidence": 0.8},
                {"type": "hangul", "matched": ["한국"]},
            ]
        )
        self.assertEqual(a["alert_level"], "nsfw+korea")
        self.assertTrue(a["has_nsfw"] and a["has_korea"])


class TestOCRHangulPath(unittest.TestCase):
    def test_analyze_text_hangul_threshold(self):
        ocr = OCRDetector(ENGLISH_KW, CUSTOM_KW, min_hangul_conf=0.55)
        # Text-only path needs >= 4 Hangul chars
        weak = ocr.detect_text("가나다")  # 3 chars
        self.assertFalse(any(d["type"] == "hangul" for d in weak))
        strong = ocr.detect_text("가나다라 테스트")
        self.assertTrue(any(d["type"] == "hangul" for d in strong))

    def test_ocr_translate_drops_hangul_keeps_keyword(self):
        ocr = OCRDetector(ENGLISH_KW, CUSTOM_KW)
        hits = ocr.detect_text("Google Translate 안녕하세요 Seoul news")
        types = {h["type"] for h in hits}
        self.assertNotIn("hangul", types)
        self.assertIn("english_keyword", types)


class TestNewDataWatcher(unittest.TestCase):
    def test_deferral_keeps_unseen_until_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "10.0.0.1"
            host.mkdir()
            # Create 3 fake images
            paths = []
            for i in range(3):
                p = host / f"shot_{i}.jpg"
                Image.new("RGB", (8, 8), (i * 40, 0, 0)).save(p)
                paths.append(str(p))

            w = RecordingWatcher(root)
            w.initialize()
            # Clear known so all are "new"
            w._known_files.clear()

            first = w.get_new_files()
            self.assertEqual(len(first), 3)
            # Without mark_seen, same files again
            again = w.get_new_files()
            self.assertEqual(len(again), 3)

            # Mark only first two (simulate poll limit kept 2)
            w.mark_seen([first[0]["path"], first[1]["path"]])
            left = w.get_new_files()
            self.assertEqual(len(left), 1)
            self.assertEqual(left[0]["path"], first[2]["path"])


class TestNSFWSmoke(unittest.TestCase):
    def test_engines_available(self):
        self.assertTrue(opennsfw_available())

    def test_safe_image_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "safe.jpg"
            # Plain blue image should not trigger NSFW
            Image.new("RGB", (224, 224), (30, 80, 180)).save(p, quality=90)
            det = NSFWDetector(threshold=0.4, engine="both")
            result = det.detect_file(p)
            self.assertIsNone(result)

    def test_opennsfw_only_returns_score_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "safe2.jpg"
            Image.new("RGB", (224, 224), (200, 200, 200)).save(p)
            det = NSFWDetector(threshold=0.99, engine="opennsfw")
            # Extremely high threshold → safe
            self.assertIsNone(det.detect_file(p))


class TestScanStateCursor(unittest.TestCase):
    def test_reset_cursors_and_query_semantics(self):
        from autolook.db.incident_db import AlertStore

        with tempfile.TemporaryDirectory() as tmp:
            db = AlertStore(Path(tmp) / "inc.db")
            try:
                db.reset_cursors_to_now()
                state = db.get_scan_state()
                self.assertIn("last_weblog_time", state)
                self.assertRegex(state["last_weblog_time"], r"^\d{4}-\d{2}-\d{2}")
                since = state["last_weblog_time"]
                self.assertTrue(since < "2099-01-01 00:00:00")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
