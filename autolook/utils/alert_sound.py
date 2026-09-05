"""Play an alert sound (Windows), with short debounce."""

import time

_last_play_ts = 0.0
_MIN_GAP_SEC = 15.0


def play_alert_sound():
    """Async system alert. No-op if sound APIs are unavailable.

    Debounced so a long video scan with many hits does not spam the speaker.
    """
    global _last_play_ts
    now = time.monotonic()
    if now - _last_play_ts < _MIN_GAP_SEC:
        return
    _last_play_ts = now
    try:
        import winsound
        winsound.PlaySound(
            "SystemExclamation",
            winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
    except Exception:
        try:
            import sys
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass
