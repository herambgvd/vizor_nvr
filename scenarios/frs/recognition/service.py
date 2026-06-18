"""Recognition service: ONNX engine singleton + embed / detect / recognize.

Wraps the ported inference pipeline (inference/) into the plugin's domain calls.
Real SCRFD + ArcFace when models are mounted; deterministic histogram embedding
fallback otherwise, so the API works end to end either way.
"""
from __future__ import annotations

import io
import math
from typing import Any

from PIL import Image

import config
from qdrant import store as qdrant_store
from db import session
from db.models import FRSPerson

try:
    import cv2
    import numpy as np
except Exception:  # noqa: BLE001
    cv2 = None
    np = None

try:
    import onnxruntime as ort
except Exception:  # noqa: BLE001
    ort = None

try:
    from recognition.inference.engine import OnnxEngine
    from recognition.inference.align import align_face
    from recognition.inference.augment import generate_photometric_variants
    from recognition.inference.quality import (
        crop_face_with_margin,
        estimate_pose_from_landmarks,
        face_sharpness,
        is_face_usable,
    )
except Exception as _exc:  # noqa: BLE001
    OnnxEngine = None
    print(f"[frs] inference pipeline import failed, histogram fallback only: {_exc}", flush=True)

_ENGINE = None  # lazily-built OnnxEngine singleton


def engine():
    """Lazy OnnxEngine singleton. None if the inference package failed to import."""
    global _ENGINE
    if _ENGINE is not None or OnnxEngine is None:
        return _ENGINE
    _ENGINE = OnnxEngine(config.DETECTOR_MODEL_PATH, config.EMBED_MODEL_PATH,
                         config.ANTISPOOF_MODEL_PATH, config.FAIRFACE_MODEL_PATH)
    return _ENGINE


def engine_ready() -> bool:
    eng = engine()
    return bool(eng and eng.ready)


def onnx_status() -> dict[str, Any]:
    eng = engine()
    if eng is not None:
        st = eng.status()
        st["backend"] = config.INFERENCE_BACKEND
        st["note"] = ("Real SCRFD + ArcFace pipeline (ported from vizor-gpu). A deterministic "
                      "histogram embedding fallback is used while model files are absent.")
        return st
    return {
        "backend": config.INFERENCE_BACKEND,
        "runtime_available": ort is not None,
        "ready": False,
        "note": "Inference package unavailable; histogram fallback only.",
    }


def _bgr_from_bytes(data: bytes):
    if cv2 is None or np is None:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _histogram_embedding(data: bytes) -> list[float]:
    """Deterministic color-histogram + grid fallback (512-d) used when the ONNX
    models are not mounted, so enroll/recognize work end to end regardless."""
    image = Image.open(io.BytesIO(data)).convert("RGB").resize((96, 96))
    pixels = list(image.getdata())
    bins = [0.0] * 48
    for r, g, b in pixels:
        bins[r // 16] += 1.0
        bins[16 + g // 16] += 1.0
        bins[32 + b // 16] += 1.0
    total = float(len(pixels) * 3) or 1.0
    hist = [x / total for x in bins]
    cells: list[float] = []
    grid = image.resize((64, 64))
    for y in range(0, 64, 8):
        for x in range(0, 64, 8):
            crop = grid.crop((x, y, x + 8, y + 8))
            px = list(crop.getdata())
            cells.append(sum(r for r, _g, _b in px) / (len(px) * 255.0))
    vector = (hist + cells)[:config.VECTOR_SIZE]
    if len(vector) < config.VECTOR_SIZE:
        vector.extend([0.0] * (config.VECTOR_SIZE - len(vector)))
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def detect_faces(data: bytes) -> tuple[list[dict], int, int]:
    """Return (detections, width, height). Empty list if engine not ready."""
    eng = engine()
    image = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = image.size
    if not (eng and eng.ready):
        return [], w, h
    frame = _bgr_from_bytes(data)
    if frame is None:
        return [], w, h
    return eng.detect_faces(frame, conf_thresh=config.DET_CONF_THRESHOLD), w, h


def _match_vector(vector: list[float], threshold: float) -> dict | None:
    """Top Qdrant match for an embedding, or None below threshold."""
    hits = qdrant_store.search(vector, limit=10)
    best = None
    for h in hits:
        score = float(h.get("score", 0.0))
        if score < threshold:
            continue
        if best is None or score > best["confidence"]:
            best = {"person_id": h.get("person_id"), "person_name": h.get("person_name"),
                    "confidence": round(score, 4), "photo_id": h.get("photo_id")}
    if best and not best.get("person_name") and best.get("person_id"):
        with session() as s:
            p = s.get(FRSPerson, best["person_id"])
            best["person_name"] = p.full_name if p else None
    return best


def analyze_frame(data: bytes, min_conf: float | None = None, roi=None,
                  with_liveness: bool = False, with_demographics: bool = False,
                  gate_quality: bool = True, det_conf: float | None = None,
                  min_face_px: int | None = None, min_sharpness: float | None = None,
                  max_pose_deg: float | None = None) -> dict:
    """Full live-pipeline analysis of one frame. Returns:
        {faces: [{bbox, bbox_px, confidence(det), embedding, match,
                  liveness, demographics}], width, height, engine}
    Quality-gate thresholds are passed in (from per-camera config) so nothing is
    hard-coded; they fall back to the platform defaults in config when omitted."""
    threshold = config.SIMILARITY_THRESHOLD if min_conf is None else float(min_conf)
    g_min_px = config.LIVE_MIN_FACE_PX if min_face_px is None else int(min_face_px)
    g_min_sharp = config.LIVE_MIN_SHARPNESS if min_sharpness is None else float(min_sharpness)
    g_max_pose = config.LIVE_MAX_POSE_DEG if max_pose_deg is None else float(max_pose_deg)
    eng = engine()
    image = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = image.size

    if not (eng and eng.ready):
        # Fallback: whole-frame histogram embedding, no real detection.
        vec = _histogram_embedding(data)
        return {"faces": [{"bbox": None, "bbox_px": None, "confidence": 0.9,
                           "embedding": vec, "match": _match_vector(vec, threshold),
                           "liveness": None, "demographics": None}],
                "width": w, "height": h, "engine": "histogram"}

    frame = _bgr_from_bytes(data)
    if frame is None:
        return {"faces": [], "width": w, "height": h, "engine": "arcface"}
    conf = (config.LIVE_DET_CONF if det_conf is None else float(det_conf)) if gate_quality else config.DET_CONF_THRESHOLD
    dets = eng.detect_faces(frame, conf_thresh=conf)
    faces = []
    for d in dets:
        bbox_px = list(map(float, d["bbox"]))
        cx = (bbox_px[0] + bbox_px[2]) / 2 / w
        cy = (bbox_px[1] + bbox_px[3]) / 2 / h
        if roi and not _point_in_any_roi(cx, cy, roi):
            continue
        # Live quality gates (vizor-gpu parity): drop tiny / edge-clipped /
        # bad-aspect / blurry / steep faces so only clean faces produce events.
        if gate_quality:
            ok, _reason = is_face_usable(d["bbox"], w, h, min_face_px=g_min_px)
            if not ok:
                continue
            crop_q = crop_face_with_margin(frame, d["bbox"], w, h)
            if face_sharpness(crop_q) < g_min_sharp:
                continue
            lms_g = d.get("landmarks")
            if lms_g is not None:
                yaw_g, pitch_g, _r = estimate_pose_from_landmarks(lms_g)
                if max(yaw_g, pitch_g) > g_max_pose:
                    continue
        aligned = align_face(frame, d["bbox"], d.get("landmarks"), w, h)
        vec = eng.embed_face(aligned)
        if vec is None:
            continue
        vec = vec.tolist()
        face = {
            "bbox": [bbox_px[0] / w, bbox_px[1] / h, bbox_px[2] / w, bbox_px[3] / h],
            "bbox_px": bbox_px,
            "confidence": float(d["confidence"]),
            "embedding": vec,
            "match": _match_vector(vec, threshold),
            "liveness": None,
            "demographics": None,
        }
        if with_liveness:
            try:
                crop = crop_face_with_margin(frame, d["bbox"], w, h)
                face["liveness"] = eng.liveness(crop)
            except Exception:  # noqa: BLE001
                face["liveness"] = None
        if with_demographics:
            # Demographics (esp. gender) are only reliable on roughly frontal
            # faces — FairFace mis-predicts on steep/tilted crops (this camera is
            # top-down). Gate on pose so a bad angle yields no demographics
            # instead of a confident-but-wrong label.
            try:
                lms = d.get("landmarks")
                pose_ok = True
                if lms is not None:
                    yaw, pitch, roll = estimate_pose_from_landmarks(lms)
                    pose_ok = max(yaw, pitch, roll) <= config.ENROLL_MAX_POSE_DEG
                if pose_ok:
                    crop = crop_face_with_margin(frame, d["bbox"], w, h)
                    face["demographics"] = eng.age_gender(crop)
            except Exception:  # noqa: BLE001
                face["demographics"] = None
        faces.append(face)
    return {"faces": faces, "width": w, "height": h, "engine": "arcface"}


def _point_in_any_roi(px: float, py: float, polygons) -> bool:
    """Ray-cast point-in-polygon over normalised [[x,y],...] polygons."""
    for poly in polygons or []:
        pts = poly.get("points") if isinstance(poly, dict) else poly
        if not pts or len(pts) < 3:
            continue
        inside = False
        n = len(pts)
        j = n - 1
        for i in range(n):
            xi, yi = pts[i][0], pts[i][1]
            xj, yj = pts[j][0], pts[j][1]
            if (yi > py) != (yj > py):
                xint = (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
                if px < xint:
                    inside = not inside
            j = i
        if inside:
            return True
    return False


def embed_largest_face(data: bytes, gate: bool = False) -> tuple[list[float] | None, dict[str, Any]]:
    """Real pipeline: decode → SCRFD detect → largest face → (optional quality
    gate) → align → ArcFace 512-d embedding. Returns (vector, meta); vector is
    None when no usable face is found. Histogram fallback when engine not ready."""
    meta: dict[str, Any] = {"engine": "arcface"}
    eng = engine()
    if not (eng and eng.ready):
        return _histogram_embedding(data), {"engine": "histogram"}
    frame = _bgr_from_bytes(data)
    if frame is None:
        return None, {"engine": "arcface", "error": "decode_failed"}
    h, w = frame.shape[:2]
    dets = eng.detect_faces(frame, conf_thresh=config.DET_CONF_THRESHOLD)
    if not dets:
        return None, {"engine": "arcface", "error": "no_face"}
    det = max(dets, key=lambda d: float((d["bbox"][2] - d["bbox"][0]) * (d["bbox"][3] - d["bbox"][1])))
    bbox = det["bbox"]
    meta["confidence"] = det["confidence"]
    # Normalised bbox (x1,y1,x2,y2 in 0..1) so callers can crop / overlay.
    meta["bbox"] = [float(bbox[0] / w), float(bbox[1] / h), float(bbox[2] / w), float(bbox[3] / h)]
    meta["bbox_px"] = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    if gate:
        ok, reason = is_face_usable(bbox, w, h, min_face_px=config.ENROLL_MIN_FACE_PX)
        if not ok:
            return None, {"engine": "arcface", "error": f"quality_{reason}"}
        crop = crop_face_with_margin(frame, bbox, w, h)
        sharp = face_sharpness(crop)
        if sharp < config.ENROLL_MIN_SHARPNESS:
            return None, {"engine": "arcface", "error": "blurry", "sharpness": sharp}
        yaw, pitch, _roll = estimate_pose_from_landmarks(det["landmarks"])
        if max(yaw, pitch) > config.ENROLL_MAX_POSE_DEG:
            return None, {"engine": "arcface", "error": "bad_pose", "yaw": yaw, "pitch": pitch}
        meta["sharpness"] = sharp
    aligned = align_face(frame, bbox, det.get("landmarks"), w, h)
    vec = eng.embed_face(aligned)
    if vec is None:
        return None, {"engine": "arcface", "error": "embed_failed"}
    meta["aligned"] = aligned
    return vec.tolist(), meta


def query_embedding(data: bytes) -> list[float]:
    """512-d embedding for recognition/investigate queries (real or fallback)."""
    vec, _meta = embed_largest_face(data, gate=False)
    return vec if vec is not None else _histogram_embedding(data)


def augment_points(aligned) -> list[dict]:
    """Photometric variants for an aligned crop → [{"image","tag"}]. Empty if
    the engine or aligned crop is unavailable."""
    if not engine_ready() or aligned is None or OnnxEngine is None:
        return []
    return generate_photometric_variants(aligned)


def recognize(data: bytes, min_conf: float | None = None) -> dict[str, Any]:
    """Embed the query face and match against the enrolled gallery in Qdrant.
    Cosine score >= threshold = recognized. Collapses augment hits to one row
    per person, keeping the best score."""
    threshold = config.SIMILARITY_THRESHOLD if min_conf is None else float(min_conf)
    vec, meta = embed_largest_face(data, gate=False)
    vector = vec if vec is not None else _histogram_embedding(data)
    query_bbox = meta.get("bbox")          # normalised query-face box (or None)
    query_bbox_px = meta.get("bbox_px")
    hits = qdrant_store.search(vector, limit=30)
    best_by_person: dict[str, dict[str, Any]] = {}
    for h in hits:
        score = float(h.get("score", 0.0))
        if score < threshold:
            continue
        pid = h.get("person_id")
        if not pid:
            continue
        prev = best_by_person.get(pid)
        if prev is None or score > prev["confidence"]:
            best_by_person[pid] = {
                "person_id": pid, "person_name": h.get("person_name"),
                "confidence": round(score, 4), "photo_id": h.get("photo_id"),
            }
    matches = sorted(best_by_person.values(), key=lambda m: m["confidence"], reverse=True)
    with session() as s:
        for m in matches:
            if not m.get("person_name"):
                person = s.get(FRSPerson, m["person_id"])
                m["person_name"] = person.full_name if person else None
    # face_present = a face was actually detected in the query frame (real engine
    # only — the histogram fallback has no detector, so treat its embedding as
    # "present" too). Lets the live worker emit face_unknown when a face is seen
    # but matches nobody.
    face_present = (meta.get("bbox") is not None) or (meta.get("engine") == "histogram")
    return {"matches": matches, "match_count": len(matches), "face_present": face_present,
            "bbox": query_bbox, "bbox_px": query_bbox_px}
