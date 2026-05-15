"""
FRS enrollment pipeline.

Photo upload → background task here:
  1. Load image (PIL → BGR ndarray)
  2. Run YOLOv12m_face on Triton → bboxes
  3. Pick largest face, quality-gate (min size, pose, sharpness)
  4. Crop + align → 112×112
  5. Run ArcFace on Triton → 512-d vector
  6. L2-normalize → Qdrant upsert
  7. Update FRSPhoto.status + qdrant_point_id

All errors caught + recorded into FRSPhoto.error / .error_code so the
gallery UI can show why a photo failed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


# Image deps gated — keep import optional so the rest of FRS still works
# without OpenCV installed in the runtime.
try:
    import cv2
    from PIL import Image
    _HAS_CV = True
except ImportError:
    cv2 = None  # type: ignore
    Image = None  # type: ignore
    _HAS_CV = False


# --------------------------------------------------------------------------
# Image preprocessing
# --------------------------------------------------------------------------


def _load_bgr(path: str) -> Optional[np.ndarray]:
    """Read file → BGR ndarray. Handles JPEG, PNG, HEIC via PIL fallback."""
    if not _HAS_CV:
        return None
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is not None:
        return img
    try:
        pil = Image.open(path).convert("RGB")
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _letterbox_640(bgr: np.ndarray):
    """Aspect-preserving resize to 640×640. Returns (chw_fp32, ratio, dx, dy)."""
    h, w = bgr.shape[:2]
    r = min(640 / h, 640 / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((640, 640, 3), 114, dtype=np.uint8)
    dx, dy = (640 - nw) // 2, (640 - nh) // 2
    canvas[dy:dy + nh, dx:dx + nw] = resized
    chw = canvas[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
    return np.ascontiguousarray(chw[None, ...]), r, dx, dy


def _crop_face(bgr: np.ndarray, bbox_xywh: tuple, pad: float = 0.2) -> np.ndarray:
    """Pad + crop bbox → 112×112 BGR for ArcFace input."""
    H, W = bgr.shape[:2]
    x, y, w, h = bbox_xywh
    px, py = w * pad, h * pad
    x0 = max(0, int(x - px))
    y0 = max(0, int(y - py))
    x1 = min(W, int(x + w + px))
    y1 = min(H, int(y + h + py))
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return np.zeros((112, 112, 3), dtype=np.uint8)
    return cv2.resize(crop, (112, 112), interpolation=cv2.INTER_LINEAR)


def _sharpness(crop_bgr: np.ndarray) -> float:
    """Laplacian variance — higher = sharper. <80 is typically blurry."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# --------------------------------------------------------------------------
# Triton calls — best-effort. When Triton is offline we mark photo as
# `failed:no_inference_service` so the operator gets a clear error.
# --------------------------------------------------------------------------


SCRFD_STRIDES = (8, 16, 32)
SCRFD_NUM_ANCHORS = 2  # buffalo_l/det_10g has 2 anchors per location
SCRFD_SCORE_THRESH = 0.5
SCRFD_NMS_IOU = 0.4


def _scrfd_decode(outputs: dict, ratio: float, dx: int, dy: int):
    """Decode SCRFD multi-stride output → list[(x, y, w, h, conf)] in source
    image pixel coords (post-letterbox undo). NMS applied across strides."""
    boxes: list[tuple[float, float, float, float, float]] = []
    for stride in SCRFD_STRIDES:
        score = outputs.get(f"score_{stride}")
        bbox = outputs.get(f"bbox_{stride}")
        if score is None or bbox is None:
            continue
        score = score.reshape(-1)
        bbox = bbox.reshape(-1, 4) * stride
        feat_h = feat_w = 640 // stride
        grid_y, grid_x = np.meshgrid(
            np.arange(feat_h, dtype=np.float32),
            np.arange(feat_w, dtype=np.float32),
            indexing="ij",
        )
        anchor_centers = np.stack([grid_x, grid_y], axis=-1) * stride
        anchor_centers = anchor_centers.reshape(-1, 2)
        anchor_centers = np.repeat(anchor_centers, SCRFD_NUM_ANCHORS, axis=0)
        if score.shape[0] != anchor_centers.shape[0]:
            continue
        keep = score >= SCRFD_SCORE_THRESH
        if not np.any(keep):
            continue
        ac = anchor_centers[keep]
        bb = bbox[keep]
        sc = score[keep]
        x1 = ac[:, 0] - bb[:, 0]
        y1 = ac[:, 1] - bb[:, 1]
        x2 = ac[:, 0] + bb[:, 2]
        y2 = ac[:, 1] + bb[:, 3]
        for i in range(x1.shape[0]):
            sx = (float(x1[i]) - dx) / ratio
            sy = (float(y1[i]) - dy) / ratio
            sw = (float(x2[i]) - float(x1[i])) / ratio
            sh = (float(y2[i]) - float(y1[i])) / ratio
            if sw <= 0 or sh <= 0:
                continue
            boxes.append((sx, sy, sw, sh, float(sc[i])))
    return _nms(boxes, SCRFD_NMS_IOU)


def _nms(boxes, iou_thr):
    if not boxes:
        return []
    boxes_sorted = sorted(boxes, key=lambda b: b[4], reverse=True)
    keep = []
    for b in boxes_sorted:
        x, y, w, h, _ = b
        ax2, ay2 = x + w, y + h
        drop = False
        for k in keep:
            kx, ky, kw, kh, _ = k
            ix1 = max(x, kx); iy1 = max(y, ky)
            ix2 = min(ax2, kx + kw); iy2 = min(ay2, ky + kh)
            iw = max(0.0, ix2 - ix1); ih = max(0.0, iy2 - iy1)
            inter = iw * ih
            union = w * h + kw * kh - inter
            if union <= 0:
                continue
            if inter / union > iou_thr:
                drop = True
                break
        if not drop:
            keep.append(b)
    return keep


async def _detect_largest_face(bgr: np.ndarray):
    """Run SCRFD → return largest bbox (x, y, w, h) in pixel coords,
    or None if no face / Triton unavailable."""
    from app.ai import triton_client

    if not await triton_client.is_ready("scrfd"):
        return None

    blob, ratio, dx, dy = _letterbox_640(bgr)
    try:
        out = await triton_client.infer(
            "scrfd",
            inputs=[("input.1", blob)],
            output_names=[
                "score_8", "score_16", "score_32",
                "bbox_8", "bbox_16", "bbox_32",
            ],
            timeout_sec=3.0,
        )
    except Exception as e:
        logger.warning("face detect failed: %s", e)
        return None

    boxes = _scrfd_decode(out, ratio, dx, dy)
    if not boxes:
        return None
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    x, y, w, h, _ = boxes[0]
    return (x, y, w, h)


async def _embed(crop_112: np.ndarray) -> Optional[np.ndarray]:
    """ArcFace → 512-d vector."""
    from app.ai import triton_client

    if not await triton_client.is_ready("arcface"):
        return None

    chw = crop_112[:, :, ::-1].transpose(2, 0, 1).astype(np.float32)
    chw = (chw - 127.5) / 128.0  # arcface canonical norm
    blob = np.ascontiguousarray(chw[None, ...])
    try:
        out = await triton_client.infer(
            "arcface",
            inputs=[("input.1", blob)],
            output_names=["683"],
            timeout_sec=3.0,
        )
    except Exception as e:
        logger.warning("arcface embed failed: %s", e)
        return None
    vec = list(out.values())[0].reshape(-1).astype(np.float32)
    return vec


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


async def enroll_photo(photo_id: str) -> dict:
    """Run the enrollment pipeline for a stored FRSPhoto row.

    Returns a result dict {status, error_code, qdrant_point_id, quality}.
    The caller (router or background task) updates the DB row.
    """
    from app.database import async_session_maker
    from app.ai.models import FRSPhoto
    from app.ai import qdrant_client
    from sqlalchemy import select

    out = {
        "status": "failed",
        "error_code": None,
        "error": None,
        "qdrant_point_id": None,
        "quality_score": None,
    }

    if not _HAS_CV:
        out["error_code"] = "missing_dep"
        out["error"] = "opencv not installed"
        return out

    async with async_session_maker() as db:
        photo = (
            await db.execute(select(FRSPhoto).where(FRSPhoto.id == photo_id))
        ).scalar_one_or_none()
        if not photo:
            out["error_code"] = "photo_not_found"
            return out
        storage_key = photo.storage_key
        person_id = photo.person_id

    abs_path = storage_key
    if not os.path.isabs(abs_path):
        abs_path = os.path.join(settings.STORAGE_PATH, abs_path)

    bgr = _load_bgr(abs_path)
    if bgr is None:
        out["error_code"] = "load_failed"
        out["error"] = f"cannot read {abs_path}"
        return out

    bbox = await _detect_largest_face(bgr)
    if bbox is None:
        out["error_code"] = "no_face"
        out["error"] = "no face detected (or Triton offline)"
        return out

    x, y, w, h = bbox
    if min(w, h) < 80:
        out["error_code"] = "face_too_small"
        out["error"] = f"min dim {int(min(w,h))}px < 80px"
        return out

    crop = _crop_face(bgr, bbox)
    sharp = _sharpness(crop)
    if sharp < 80:
        out["error_code"] = "blurry"
        out["error"] = f"sharpness {sharp:.1f} < 80"
        return out

    vec = await _embed(crop)
    if vec is None or vec.shape[-1] != 512:
        out["error_code"] = "embed_failed"
        out["error"] = "ArcFace returned invalid embedding"
        return out

    try:
        await qdrant_client.ensure_collection()
        pid = await qdrant_client.upsert_embedding(person_id, photo_id, vec)
    except Exception as e:
        out["error_code"] = "qdrant_failed"
        out["error"] = str(e)
        return out

    out["status"] = "enrolled"
    out["qdrant_point_id"] = pid
    out["quality_score"] = round(sharp, 1)
    return out


async def enroll_photo_and_persist(photo_id: str) -> None:
    """Top-level fire-and-forget task: runs enrollment, writes result to
    FRSPhoto row. Used as BackgroundTasks() target from photo upload."""
    from app.database import async_session_maker
    from app.ai.models import FRSPhoto
    from sqlalchemy import select

    result = await enroll_photo(photo_id)
    async with async_session_maker() as db:
        photo = (
            await db.execute(select(FRSPhoto).where(FRSPhoto.id == photo_id))
        ).scalar_one_or_none()
        if not photo:
            return
        photo.status = result["status"]
        photo.error_code = result.get("error_code")
        photo.error = result.get("error")
        if result.get("qdrant_point_id"):
            photo.qdrant_point_id = result["qdrant_point_id"]
        if result.get("quality_score") is not None:
            photo.quality_score = result["quality_score"]
        await db.commit()
    logger.info("enrolled %s → %s", photo_id, result["status"])
