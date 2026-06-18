"""Quality-gate helpers ported from vizor-gpu ai_workers/frs/inference/quality.py.

Sharpness (Laplacian variance), 5-point-landmark pose estimate, geometry gate,
safe crops. CPU, numpy/OpenCV only.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


LIVE_MIN_SHARPNESS = 60.0
LIVE_MAX_POSE_DEG = 40.0
LIVE_MIN_FACE_PX = 80.0
LIVE_EDGE_MARGIN_PX = 8.0
LIVE_ASPECT_MIN = 0.6
LIVE_ASPECT_MAX = 1.6
LIVE_HIGH_CONF_SCORE = 0.75


def is_face_usable(
    bbox: np.ndarray,
    fw: int,
    fh: int,
    min_face_px: float = LIVE_MIN_FACE_PX,
    edge_margin_px: float = LIVE_EDGE_MARGIN_PX,
    aspect_min: float = LIVE_ASPECT_MIN,
    aspect_max: float = LIVE_ASPECT_MAX,
) -> tuple[bool, str]:
    """Pre-recognition quality gate on bbox geometry. Returns (ok, reason)."""
    x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    bw = x2 - x1
    bh = y2 - y1
    if bw < min_face_px or bh < min_face_px:
        return False, "too_small"
    if x1 < edge_margin_px or y1 < edge_margin_px:
        return False, "edge_clip"
    if x2 > (fw - edge_margin_px) or y2 > (fh - edge_margin_px):
        return False, "edge_clip"
    aspect = bw / max(bh, 1e-6)
    if aspect < aspect_min or aspect > aspect_max:
        return False, "bad_aspect"
    return True, ""


def face_sharpness(crop: np.ndarray) -> float:
    """Laplacian variance of the face crop's luminance channel."""
    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def estimate_pose_from_landmarks(landmarks: np.ndarray) -> tuple[float, float, float]:
    """Yaw, pitch, roll (degrees, all positive) from 5-point landmarks.

    Landmark order: right_eye, left_eye, nose_tip, right_mouth, left_mouth.
    """
    right_eye = landmarks[0]
    left_eye = landmarks[1]
    nose = landmarks[2]
    right_mouth = landmarks[3]
    left_mouth = landmarks[4]

    eye_center = (left_eye + right_eye) / 2.0
    mouth_center = (left_mouth + right_mouth) / 2.0
    eye_distance = float(np.linalg.norm(right_eye - left_eye))
    if eye_distance < 1e-3:
        return 0.0, 0.0, 0.0

    roll_rad = math.atan2(
        float(left_eye[1] - right_eye[1]),
        float(left_eye[0] - right_eye[0]),
    )
    roll_deg = abs(math.degrees(roll_rad))

    lateral_offset = float(nose[0] - eye_center[0])
    yaw_sin = max(-1.0, min(1.0, lateral_offset / (eye_distance * 0.6)))
    yaw_deg = abs(math.degrees(math.asin(yaw_sin)))

    face_height = float(mouth_center[1] - eye_center[1])
    if face_height < 1e-3:
        pitch_deg = 0.0
    else:
        expected_nose_y = eye_center[1] + 0.55 * face_height
        pitch_ratio = float(nose[1] - expected_nose_y) / face_height
        pitch_ratio = max(-1.0, min(1.0, pitch_ratio * 2.0))
        pitch_deg = abs(math.degrees(math.asin(pitch_ratio)))

    return yaw_deg, pitch_deg, roll_deg


def crop_face(frame: np.ndarray, bbox: np.ndarray, fw: int, fh: int) -> np.ndarray:
    """Safe int crop, clamped to frame bounds. Empty array on degenerate box."""
    x1, y1, x2, y2 = bbox.astype(int)
    x1, y1 = max(0, x1), max(0, y1)
    x2 = min(fw, max(x1 + 1, x2))
    y2 = min(fh, max(y1 + 1, y2))
    return frame[y1:y2, x1:x2]


def crop_face_with_margin(
    frame: np.ndarray, bbox: np.ndarray, fw: int, fh: int, margin_frac: float = 0.2,
) -> np.ndarray:
    x1, y1, x2, y2 = bbox.astype(int)
    bw, bh = x2 - x1, y2 - y1
    margin = int(max(bw, bh) * margin_frac)
    x1 = max(0, x1 - margin)
    y1 = max(0, y1 - margin)
    x2 = min(fw, x2 + margin)
    y2 = min(fh, y2 + margin)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return np.zeros((80, 80, 3), dtype=np.uint8)
    return crop
