# Suspect Search — Eocortex-Parity Overhaul Plan

## Goal

Match Eocortex-style suspect search:
- **Stage 1 (attribute query):** operator picks top-wear (type + color), bottom-wear
  (type + color), gender, age band, accessories, a **time range**, and camera(s)
  → all matching person sightings in that window.
- **Stage 2 (image refine):** pick a person from results (or upload) → ReID finds
  more sightings of that specific person across footage (body/clothes, face
  optional).

## Current state (from audit)

Already present: 2-stage ReID architecture (index → Qdrant cosine →
`search-similar`), camera filter, results UI + movement timeline, color heuristic
(top/bottom-half mean → 11-color palette).

Gaps:
1. **No garment TYPE** (shirt/jacket/pants/shorts/dress) — only crude color.
2. **No gender / age**.
3. **Accessories** only as a separate detector object, not per-person.
4. **Time-range filter is BROKEN** on indexed data — accepted by API + UI but
   never applied to the Qdrant query (`_qdrant_filter` filters only object_type +
   camera). Bug.
5. Attribute match is exact-string equality on coarse colors.

## Models (decided: ONNX-ready, light, Triton-served)

No single PAR ONNX is production-ready (OpenPAR is PyTorch research-grade, CLIP/
Mamba, heavy — rejected for 64-ch realtime). Compose attributes from light,
ONNX-exportable models on the shared Triton:

| Model | Role | Source | Output |
|-------|------|--------|--------|
| yolo26 (existing) | person + bag detect | already mounted | person boxes |
| person-reid (existing) | appearance embedding (stage-2) | already mounted | 768-d |
| **clothing-detect (NEW)** | garment TYPE + accessories | Roboflow "Clothing Detection" (classes: shirt, jacket, pants, shorts, skirt, dress, hat, shoe, bag, sunglass) → export ONNX | boxes+classes on the person crop |
| **fairface (existing in FRS)** | gender + age band | already in Triton repo | 18 logits → gender, age bucket |
| color heuristic (existing, improved) | top/bottom color | OpenCV on garment region | nearest palette color |

Color comes from the garment region the clothing model localises (not a blind
top/bottom-half split) → far better color accuracy.

## Architecture (per indexed person crop)

```
person crop (from yolo26 box)
  ├─ clothing-detect (Triton)  → garments: [{type, bbox}] → top_type, bottom_type, accessories[]
  │     └─ per garment region → dominant color → top_color, bottom_color
  ├─ fairface (Triton, on upper/face region) → gender, age_band
  └─ person-reid (Triton) → 768-d embedding  (stage-2 refine)
```

All four run on the **shared Triton** (dynamic batching across cameras). Plugin
stays a thin client (matches the FRS Triton migration).

## Work breakdown

### 1. Models on Triton
- Export the Roboflow Clothing Detection model to ONNX; drop into
  `triton/model_repository/clothing_detect/` with a `config.pbtxt`.
- fairface, scrfd, arcface already in the repo (shared from FRS).
- person-reid + yolo26 → add to the Triton repo too (suspect-search migrates off
  in-process onnxruntime, same as FRS).

### 2. Attribute extraction (plugin)
- New `services/attributes.py`: `extract_attributes(crop_bgr) -> dict` returning
  `top_type, top_color, bottom_type, bottom_color, gender, age_band,
  accessories[]` (+ per-field confidence). Replaces the color-only
  `_attributes_from_image`.
- Runs clothing-detect + fairface + region color via Triton.

### 3. Schema + Qdrant payload
- Postgres `results`: add typed columns `top_type, top_color, bottom_type,
  bottom_color, gender, age_band, accessories (JSON)` for fast SQL filtering
  (Alembic migration — suspect-search needs the same migration setup FRS got).
- Qdrant payload: add the same fields + create payload indexes for
  attribute + timestamp filtering.

### 4. Search (fix + extend)
- **Fix the time filter:** add a `timestamp` range condition to `_qdrant_filter`
  / `_filter_qdrant` using `start_time`/`end_time` (currently ignored).
- Stage-1 attribute query: filter-driven (attribute equality + time + camera),
  no image required. Add params: `top_type, top_color, bottom_type,
  bottom_color, gender, age_band, accessories[]`.
- Stage-2 `search-similar`: keep ReID cosine ranking (already wired).

### 5. UI/UX overhaul (`SuspectSearchTab.js`)
- Replace bbox-geometry "Size/Position" controls with real attribute dropdowns:
  **top-wear type + color, bottom-wear type + color, gender, age band,
  accessories (checkboxes)**.
- Make Stage-1 submit work with attributes only (no image required).
- Wire `start_time`/`end_time` to the now-fixed indexed filter.
- Explicit 2-step flow: attribute results → click person → "Search Similar"
  (stage-2). Enable the disabled "snapshot/crop from frame" source modes.
- Result cards show extracted attributes (type + color chips, gender/age badges,
  accessory icons) + playback + movement timeline.

### 6. Hardening parity with FRS
Suspect-search should get the same enterprise hardening already applied to FRS
where it has gaps (Alembic migrations, retention sweep, real /health, camera
scope on reads, audit). Audit separately; reuse the FRS helpers/patterns.

## Sequence
1. Export + add clothing-detect ONNX to Triton; add yolo26 + person-reid to
   Triton repo. Verify all load.
2. Attribute extraction module (Triton client) + unit-verify on a sample crop.
3. Schema migration + payload fields.
4. Search filter fix (time) + attribute filters.
5. UI overhaul.
6. End-to-end: index a clip → attribute query (e.g. "red top + blue bottom,
   male, 3pm–4pm, gate cam") → results → search-similar refine.
7. Suspect-search hardening parity pass.

## Non-goals (now)
- OpenPAR / CLIP-based PAR (too heavy for realtime; revisit if accuracy demands).
- Gait recognition.
