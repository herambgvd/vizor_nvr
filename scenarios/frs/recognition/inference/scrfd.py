"""SCRFD face detector preprocessing + decoder.

Ported verbatim from vizor-gpu ai_workers/frs/inference/scrfd.py. SCRFD outputs
score/bbox/kps tensors at 3 strides (8, 16, 32). The decoder converts anchor-grid
offsets back to image-space bboxes + 5-point landmarks, applies NMS, and rescales
to the original frame. Pure numpy/OpenCV — no Triton coupling.

Tuned against InsightFace `scrfd_10g_bnkps.onnx` / `scrfd_2.5g_bnkps.onnx`.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

SCRFD_SIZE = (640, 640)
_FEAT_STRIDES = (8, 16, 32)
_NUM_ANCHORS = 2  # InsightFace `bnkps` variant

# Stock InsightFace ONNX exports use numeric node names that differ between
# SCRFD variants. Map per-model logical key -> output tensor name.
_SCRFD_OUTPUT_NAMES_BY_MODEL: dict[str, dict[str, str]] = {
    "scrfd_2_5g": {
        "score_8":  "446", "score_16": "466", "score_32": "486",
        "bbox_8":   "449", "bbox_16":  "469", "bbox_32":  "489",
        "kps_8":    "452", "kps_16":   "472", "kps_32":   "492",
    },
    "scrfd_10g": {
        "score_8":  "448", "score_16": "471", "score_32": "494",
        "bbox_8":   "451", "bbox_16":  "474", "bbox_32":  "497",
        "kps_8":    "454", "kps_16":   "477", "kps_32":   "500",
    },
}


def active_model_name() -> str:
    return os.environ.get("FRS_DETECTOR_MODEL", "scrfd_10g")


def names_for(model: str | None = None) -> dict[str, str]:
    key = model or active_model_name()
    return _SCRFD_OUTPUT_NAMES_BY_MODEL.get(key, _SCRFD_OUTPUT_NAMES_BY_MODEL["scrfd_10g"])


def scrfd_output_list() -> list[str]:
    names = names_for()
    return [names[k] for k in (
        "score_8", "score_16", "score_32",
        "bbox_8",  "bbox_16",  "bbox_32",
        "kps_8",   "kps_16",   "kps_32",
    )]


_center_cache: dict[tuple[int, int, int], np.ndarray] = {}


def preprocess_scrfd(frame: np.ndarray) -> tuple[np.ndarray, float]:
    """Letterbox resize to 640x640, BGR, (x-127.5)/128. Returns (tensor, scale)."""
    h, w = frame.shape[:2]
    scale = min(SCRFD_SIZE[0] / h, SCRFD_SIZE[1] / w)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(frame, (new_w, new_h))
    canvas = np.zeros((SCRFD_SIZE[0], SCRFD_SIZE[1], 3), dtype=np.uint8)
    canvas[:new_h, :new_w] = resized

    img = canvas.astype(np.float32)
    img = (img - 127.5) / 128.0
    img = img.transpose(2, 0, 1)  # HWC -> CHW
    return img[np.newaxis].astype(np.float32), scale


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        px = points[:, 0] + distance[:, i]
        py = points[:, 1] + distance[:, i + 1]
        preds.append(px)
        preds.append(py)
    return np.stack(preds, axis=-1)


def _nms(dets: np.ndarray, iou_thresh: float) -> list[int]:
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(iou <= iou_thresh)[0]
        order = order[inds + 1]
    return keep


def postprocess_scrfd(
    result: dict,
    orig_w: int,
    orig_h: int,
    scale: float,
    conf_thresh: float = 0.5,
    nms_thresh: float = 0.4,
) -> list[dict]:
    """Decode SCRFD outputs → list of {bbox, confidence, landmarks} in orig image space."""
    scores_list, bboxes_list, kps_list = [], [], []
    input_h, input_w = SCRFD_SIZE

    for stride in _FEAT_STRIDES:
        s = result[f"score_{stride}"].reshape(-1)
        bbox_preds = result[f"bbox_{stride}"].reshape(-1, 4) * stride
        kps_preds = result[f"kps_{stride}"].reshape(-1, 10) * stride

        h_feat = input_h // stride
        w_feat = input_w // stride

        key = (stride, h_feat, w_feat)
        centers = _center_cache.get(key)
        if centers is None:
            ax = np.arange(w_feat) * stride
            ay = np.arange(h_feat) * stride
            anchor_centers = np.stack(np.meshgrid(ax, ay), axis=-1).astype(np.float32)
            anchor_centers = anchor_centers.reshape(-1, 2)
            if _NUM_ANCHORS > 1:
                anchor_centers = np.stack(
                    [anchor_centers] * _NUM_ANCHORS, axis=1
                ).reshape(-1, 2)
            _center_cache[key] = anchor_centers
            centers = anchor_centers

        keep = np.where(s >= conf_thresh)[0]
        if keep.size == 0:
            continue
        pos_centers = centers[keep]
        bboxes = _distance2bbox(pos_centers, bbox_preds[keep])
        kpss = _distance2kps(pos_centers, kps_preds[keep])
        scores_list.append(s[keep])
        bboxes_list.append(bboxes)
        kps_list.append(kpss)

    if not scores_list:
        return []
    scores = np.concatenate(scores_list)
    bboxes = np.concatenate(bboxes_list, axis=0)
    kpss = np.concatenate(kps_list, axis=0)

    bboxes /= scale
    kpss /= scale

    dets = np.hstack([bboxes, scores[:, None]]).astype(np.float32)
    keep_idx = _nms(dets, nms_thresh)

    out: list[dict] = []
    for i in keep_idx:
        x1, y1, x2, y2 = bboxes[i]
        x1 = max(0.0, min(float(x1), orig_w - 1))
        y1 = max(0.0, min(float(y1), orig_h - 1))
        x2 = max(0.0, min(float(x2), orig_w - 1))
        y2 = max(0.0, min(float(y2), orig_h - 1))
        lms = kpss[i].reshape(5, 2)
        out.append({
            "bbox": np.array([x1, y1, x2, y2], dtype=np.float32),
            "confidence": float(scores[i]),
            "landmarks": lms.astype(np.float32),
        })
    return out
