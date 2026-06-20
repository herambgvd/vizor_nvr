"""Low-light enhancement — CLAHE on luminance (ported from final_poc/anpr.py).

is_low_light(): mean-gray below threshold. enhance_lowlight(): CLAHE on the L
channel in LAB space (fast, no NL-means — real-time safe for night plates). The
worker applies this before detect/OCR when the frame is dark and the camera (or
the singleton settings) leaves low-light enhancement on."""
from __future__ import annotations

try:
    import cv2
except Exception:  # noqa: BLE001
    cv2 = None


def is_low_light(frame_bgr, thresh: float = 70.0) -> bool:
    """True when the frame's mean luminance is below `thresh` (POC default 70)."""
    if cv2 is None or frame_bgr is None:
        return False
    try:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) < thresh
    except Exception:  # noqa: BLE001
        return False


def enhance_lowlight(frame_bgr):
    """CLAHE on luminance. Returns the enhanced BGR frame (or the input unchanged
    on any failure)."""
    if cv2 is None or frame_bgr is None:
        return frame_bgr
    try:
        lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(l)
        return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    except Exception:  # noqa: BLE001
        return frame_bgr
