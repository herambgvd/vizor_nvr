"""Person attribute extraction for suspect-search (Eocortex-style).

For one person crop, produce:
  - top_type / bottom_type        (garment class from YOLOS-Fashionpedia)
  - top_rgb / bottom_rgb          (dominant RGB of each garment region, [r,g,b]+hex)
  - gender / age_band             (FairFace)
  - accessories[]                 (bag / hat / glasses …)
All inference runs on the shared Triton server. Colors are real RGB values
(perceptual match at query time), never snapped to a fixed palette of names.
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image

from .triton_client import infer

# ── YOLOS-Fashionpedia class map (46 classes) → coarse garment groups ─────────
_FASHION = {
    0: "shirt", 1: "top", 2: "sweater", 3: "cardigan", 4: "jacket", 5: "vest",
    6: "pants", 7: "shorts", 8: "skirt", 9: "coat", 10: "dress", 11: "jumpsuit",
    12: "cape", 13: "glasses", 14: "hat", 15: "headwear", 16: "tie", 17: "glove",
    18: "watch", 19: "belt", 20: "leg warmer", 21: "tights", 22: "sock",
    23: "shoe", 24: "bag", 25: "scarf", 26: "umbrella", 27: "hood", 28: "collar",
    29: "lapel", 30: "epaulette", 31: "sleeve", 32: "pocket", 33: "neckline",
    34: "buckle", 35: "zipper",
}
_TOP_CLASSES = {0, 1, 2, 3, 4, 5, 9, 12}            # shirt..coat, cape (upper body)
_BOTTOM_CLASSES = {6, 7, 8}                          # pants, shorts, skirt
_FULL_BODY = {10, 11}                                # dress, jumpsuit → top+bottom
_ACCESSORY = {13: "glasses", 14: "hat", 15: "hat", 24: "bag", 25: "scarf", 26: "umbrella"}

_CLOTHING_MODEL = "clothing_yolos"
_CLOTHING_HW = (512, 864)                             # model input height, width
_FAIRFACE_MODEL = "fairface"

# FairFace 18-logit layout: 9 age + 2 gender + 7 race. We use age + gender.
_AGE_BANDS = ["0-2", "3-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70+"]


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _dominant_rgb(image: Image.Image) -> tuple[int, int, int]:
    """Dominant RGB via a small k-means-ish bucket: take the most common of a
    quantised 4-bit-per-channel palette, then average that bucket's pixels."""
    small = image.convert("RGB").resize((32, 32))
    px = np.asarray(small).reshape(-1, 3).astype(np.int32)
    if px.size == 0:
        return (0, 0, 0)
    # Quantise to 4 bits/channel → bucket key, pick the most populated bucket.
    keys = (px[:, 0] // 16) * 256 + (px[:, 1] // 16) * 16 + (px[:, 2] // 16)
    vals, counts = np.unique(keys, return_counts=True)
    top_key = vals[int(np.argmax(counts))]
    mask = keys == top_key
    mean = px[mask].mean(axis=0)
    return (int(mean[0]), int(mean[1]), int(mean[2]))


def _color(image: Image.Image) -> dict[str, Any]:
    rgb = _dominant_rgb(image)
    return {"rgb": list(rgb), "hex": _hex(rgb)}


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _clothing(crop: Image.Image) -> dict[str, Any]:
    """Run YOLOS-Fashionpedia → per-region garment types + accessories."""
    h, w = _CLOTHING_HW
    img = crop.convert("RGB").resize((w, h))
    arr = (np.asarray(img).astype("float32") / 255.0)
    # ImageNet normalisation (YOLOS image processor default).
    mean = np.array([0.485, 0.456, 0.406], dtype="float32")
    std = np.array([0.229, 0.224, 0.225], dtype="float32")
    arr = (arr - mean) / std
    arr = np.transpose(arr, (2, 0, 1))[None, ...]
    out = infer(_CLOTHING_MODEL, {"pixel_values": arr}, ["logits", "pred_boxes"])
    result: dict[str, Any] = {"top_type": None, "bottom_type": None, "accessories": []}
    if not out:
        return result
    logits = out["logits"][0]                          # [queries, 47]
    boxes = out["pred_boxes"][0]                        # [queries, 4] cxcywh norm
    probs = _sigmoid(logits[:, :46])                    # drop no-object col
    best_cls = probs.argmax(axis=1)
    best_p = probs.max(axis=1)
    cw, ch = crop.size
    top_best = bottom_best = 0.0
    accessories: set[str] = set()
    for i in range(len(best_cls)):
        cls = int(best_cls[i]); p = float(best_p[i])
        if p < 0.30:
            continue
        if cls in _ACCESSORY:
            accessories.add(_ACCESSORY[cls])
            continue
        name = _FASHION.get(cls)
        if name is None:
            continue
        # crop region for this garment → color
        cx, cy, bw, bh = boxes[i]
        x1 = int(max(0, (cx - bw / 2) * cw)); y1 = int(max(0, (cy - bh / 2) * ch))
        x2 = int(min(cw, (cx + bw / 2) * cw)); y2 = int(min(ch, (cy + bh / 2) * ch))
        region = crop.crop((x1, y1, x2, y2)) if x2 > x1 and y2 > y1 else crop
        if cls in _FULL_BODY:
            if p > top_best:
                result["top_type"] = name; result["top_color"] = _color(region); top_best = p
            if p > bottom_best:
                result["bottom_type"] = name; result["bottom_color"] = _color(region); bottom_best = p
        elif cls in _TOP_CLASSES:
            if p > top_best:
                result["top_type"] = name; result["top_color"] = _color(region); top_best = p
        elif cls in _BOTTOM_CLASSES:
            if p > bottom_best:
                result["bottom_type"] = name; result["bottom_color"] = _color(region); bottom_best = p
    result["accessories"] = sorted(accessories)
    return result


def _gender_age(crop: Image.Image) -> dict[str, Any]:
    """FairFace gender + age band on the upper third (face region) of the crop."""
    w, h = crop.size
    face = crop.crop((0, 0, w, max(1, h // 3))).convert("RGB").resize((224, 224))
    arr = (np.asarray(face).astype("float32") / 255.0)
    mean = np.array([0.485, 0.456, 0.406], dtype="float32")
    std = np.array([0.229, 0.224, 0.225], dtype="float32")
    arr = np.transpose((arr - mean) / std, (2, 0, 1))[None, ...]
    out = infer(_FAIRFACE_MODEL, {"input": arr}, ["output"])
    if not out:
        return {"gender": None, "age_band": None}
    logits = np.asarray(out["output"]).reshape(-1)
    if logits.size < 11:
        return {"gender": None, "age_band": None}
    age_idx = int(np.argmax(logits[0:9]))
    gender = "male" if logits[9] > logits[10] else "female"
    return {"gender": gender, "age_band": _AGE_BANDS[age_idx]}


def extract_attributes(crop_bytes: bytes, object_type: str = "person") -> dict[str, Any]:
    """Full attribute set for one person crop. Falls back to whole-crop color if
    the clothing model produced no region. Non-person objects → color only."""
    image = Image.open(io.BytesIO(crop_bytes)).convert("RGB")
    if object_type != "person":
        return {"dominant_color": _color(image)}
    attrs = _clothing(image)
    # Fallbacks so colour is always present even if garment detection missed.
    if "top_color" not in attrs:
        attrs["top_color"] = _color(image.crop((0, 0, image.width, max(1, image.height // 2))))
    if "bottom_color" not in attrs:
        attrs["bottom_color"] = _color(image.crop((0, image.height // 2, image.width, image.height)))
    attrs["dominant_color"] = _color(image)
    attrs.update(_gender_age(image))
    return attrs
