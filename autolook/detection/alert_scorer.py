"""Combine detection signals into NSFW / Korea alert kinds."""

from typing import Optional

# Stored in incidents.alert_level (legacy column name)
KIND_NSFW = "nsfw"
KIND_KOREA = "korea"
KIND_BOTH = "nsfw+korea"

KOREA_TYPES = {"hangul", "english_keyword", "custom_keyword", "korean_domain"}


class AlertScorer:
    """Combines detection signals into NSFW / Korea kinds."""

    def score(self, detections: list[dict]) -> Optional[dict]:
        """Produce an alert with alert_level = kind (nsfw / korea / nsfw+korea).

        Returns None if no NSFW or Korea signal (watched-site-only is ignored).
        """
        if not detections:
            return None

        types = {d.get("type", "") for d in detections}
        has_nsfw = "nsfw" in types
        has_korea = bool(types & KOREA_TYPES)

        if not has_nsfw and not has_korea:
            return None

        if has_nsfw and has_korea:
            kind = KIND_BOTH
            detection_type = "nsfw+korea"
        elif has_nsfw:
            kind = KIND_NSFW
            detection_type = "nsfw"
        else:
            kind = KIND_KOREA
            detection_type = "korea"

        parts = []
        for d in detections:
            dtype = d.get("type", "")
            if dtype not in KOREA_TYPES and dtype != "nsfw":
                continue
            matched = d.get("matched", "")
            if isinstance(matched, list):
                matched = ", ".join(str(m) for m in matched[:5])
            parts.append(f"{dtype}: {matched}")
        description = "; ".join(parts) if parts else detection_type

        confidences = [d["confidence"] for d in detections if "confidence" in d]
        confidence = sum(confidences) / len(confidences) if confidences else None

        return {
            "alert_level": kind,
            "detection_type": detection_type,
            "description": description[:500],
            "confidence": confidence,
            "detections": detections,
            "has_nsfw": has_nsfw,
            "has_korea": has_korea,
        }


def incident_has_nsfw(inc: dict) -> bool:
    kind = (inc.get("alert_level") or "").lower()
    dtype = (inc.get("detection_type") or "").lower()
    if kind in (KIND_NSFW, KIND_BOTH) or "nsfw" in kind:
        return True
    return "nsfw" in dtype


def incident_has_korea(inc: dict) -> bool:
    kind = (inc.get("alert_level") or "").lower()
    dtype = (inc.get("detection_type") or "").lower()
    if kind in (KIND_KOREA, KIND_BOTH) or "korea" in kind:
        return True
    return any(
        x in dtype
        for x in ("korea", "hangul", "english_keyword", "custom_keyword", "korean")
    )


def kind_label(kind: str) -> str:
    kind = (kind or "").lower()
    if kind in ("nsfw+korea", "korean_and_nsfw"):
        return "NSFW + Korea"
    if kind == "nsfw" or kind.startswith("nsfw"):
        return "NSFW"
    if kind in ("korea", "hangul_text", "english_keyword", "custom_keyword"):
        return "Korea"
    if "korea" in kind or "hangul" in kind:
        return "Korea"
    if kind in ("critical", "high"):
        return "NSFW"
    if kind == "medium":
        return "Korea"
    if kind == "low":
        return "—"
    return kind.upper() if kind else "—"
