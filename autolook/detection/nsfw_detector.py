"""NSFW image detection using OpenNSFW (Yahoo) and/or NudeNet.

OpenNSFW runs via ONNX Runtime (same Yahoo open_nsfw model as OpenNSFW2).
That works on Python 3.14 without TensorFlow/Keras. Keras `opennsfw2` is
used only if the ONNX package is missing.

Engine is chosen in Settings (admin):
  nudenet  — NudeNet body-part detector only
  opennsfw — whole-image NSFW score only
  both     — OpenNSFW + NudeNet (NudeNet always runs; OpenNSFW can still alert alone)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ENGINES = ("nudenet", "opennsfw", "both")

_opennsfw_model = None
_nudenet_classifier = None


def opennsfw_available() -> bool:
    """True if OpenNSFW ONNX or Keras OpenNSFW2 can be imported."""
    try:
        import opennsfw_onnx  # noqa: F401
        return True
    except Exception:
        pass
    try:
        import opennsfw2  # noqa: F401
        return True
    except Exception:
        return False


def _load_opennsfw():
    """Load Yahoo OpenNSFW (ONNX first, Keras OpenNSFW2 fallback)."""
    global _opennsfw_model
    if _opennsfw_model is None:
        try:
            from opennsfw_onnx import NSFWClassifier

            clf = NSFWClassifier(providers=["CPUExecutionProvider"])
            clf.warmup()
            _opennsfw_model = ("onnx", clf)
            logger.info("OpenNSFW loaded (ONNX - Yahoo open_nsfw).")
        except Exception as onnx_err:
            try:
                import opennsfw2

                if getattr(opennsfw2, "predict_image", None) is None:
                    raise ImportError("opennsfw2.predict_image missing")
                _opennsfw_model = ("keras", opennsfw2)
                logger.info("OpenNSFW2 loaded (Keras/TensorFlow).")
            except Exception:
                logger.error(
                    "OpenNSFW failed to load (ONNX: %s). "
                    "Install: pip install opennsfw-onnx onnxruntime",
                    onnx_err,
                )
                _opennsfw_model = False
    return _opennsfw_model if _opennsfw_model is not False else None


def _load_nudenet():
    """Load NudeNet classifier (lazy)."""
    global _nudenet_classifier
    if _nudenet_classifier is None:
        try:
            from nudenet import NudeDetector

            _nudenet_classifier = NudeDetector()
            logger.info("NudeNet NSFW detector loaded.")
        except Exception as e:
            logger.error(f"NudeNet failed to load — NudeNet NSFW disabled: {e}")
            _nudenet_classifier = False
    return _nudenet_classifier if _nudenet_classifier is not False else None


class NSFWDetector:
    """NSFW detection with admin-selected engine and score threshold."""

    NSFW_LABELS = {
        "FEMALE_BREAST_EXPOSED",
        "FEMALE_GENITALIA_EXPOSED",
        "MALE_GENITALIA_EXPOSED",
        "BUTTOCKS_EXPOSED",
        "ANUS_EXPOSED",
        "FEMALE_BREAST_COVERED",
    }

    EXPLICIT_LABELS = {
        "FEMALE_GENITALIA_EXPOSED",
        "MALE_GENITALIA_EXPOSED",
        "ANUS_EXPOSED",
    }

    def __init__(self, threshold: float = 0.4, engine: str = "both"):
        self.threshold = float(threshold)
        eng = (engine or "both").strip().lower()
        self.engine = eng if eng in ENGINES else "both"

    def detect_file(self, image_path: str | Path) -> Optional[dict]:
        """Run NSFW detection on an image file. None if below threshold / safe."""
        image_path = str(image_path)

        if self.engine == "nudenet":
            return self._detailed_detect(image_path)

        nsfw_score = self._fast_score(image_path)

        if self.engine == "opennsfw":
            if nsfw_score is None:
                logger.warning("OpenNSFW unavailable — falling back to NudeNet for this image")
                return self._detailed_detect(image_path)
            if nsfw_score >= self.threshold:
                return {
                    "type": "nsfw",
                    "confidence": nsfw_score,
                    "labels": [],
                    "source": "opennsfw",
                }
            return None

        # both: always run NudeNet (max recall); OpenNSFW is an extra signal
        details = self._detailed_detect(image_path)
        if details:
            if nsfw_score is not None:
                details["opennsfw_score"] = nsfw_score
            return details

        if nsfw_score is not None and nsfw_score >= self.threshold:
            return {
                "type": "nsfw",
                "confidence": nsfw_score,
                "labels": [],
                "source": "opennsfw_only",
            }

        return None

    def detect_image_array(self, image_array, temp_path: Optional[str] = None) -> Optional[dict]:
        """Run NSFW detection on a numpy image array."""
        if temp_path:
            try:
                from PIL import Image

                img = Image.fromarray(image_array)
                img.save(temp_path, "JPEG", quality=85)
                return self.detect_file(temp_path)
            except Exception as e:
                logger.error(f"Failed to save temp image: {e}")
                return None
        return None

    def _fast_score(self, image_path: str) -> Optional[float]:
        """Yahoo OpenNSFW NSFW probability (0–1)."""
        model = _load_opennsfw()
        if model is None:
            return None
        kind, impl = model
        try:
            if kind == "onnx":
                pred = impl.classify(image_path)
                return float(pred.nsfw)
            return float(impl.predict_image(image_path))
        except Exception as e:
            logger.error(f"OpenNSFW error: {e}")
            return None

    def _detailed_detect(self, image_path: str) -> Optional[dict]:
        """Run NudeNet detailed detection using the admin threshold."""
        detector = _load_nudenet()
        if detector is None:
            return None
        try:
            results = detector.detect(image_path)
            nsfw_results = [
                r
                for r in results
                if r.get("class") in self.NSFW_LABELS and r.get("score", 0) >= self.threshold
            ]
            if not nsfw_results:
                return None

            labels = [r.get("class") for r in nsfw_results]
            max_score = max(r.get("score", 0) for r in nsfw_results)
            is_explicit = any(r.get("class") in self.EXPLICIT_LABELS for r in nsfw_results)

            return {
                "type": "nsfw",
                "confidence": max_score,
                "labels": labels,
                "is_explicit": is_explicit,
                "detail_count": len(nsfw_results),
                "source": "nudenet",
            }
        except Exception as e:
            logger.error(f"NudeNet error: {e}")
            return None
