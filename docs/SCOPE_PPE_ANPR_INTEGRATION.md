# Scope of Work — PPE + ANPR Integration into Vizor NVR

Target platform: **`vizor_nvr/scenarios/`** (the FastAPI + Triton scenario SDK).
FRS and Suspect Search already run here on shared Triton; PPE and ANPR follow the
same pattern. POC algorithms are proven and reused; only the **models + logic**
are ported, wrapped as Triton-backed per-camera workers like FRS.

Sources analysed:
- PPE POC: `/home/gvd-ai/ai_work/ppe` (single-script Python, YOLO26n + DINOv2 verifier).
- ANPR POC: `/home/gvd-ai/anpr` (`final_poc` Python + `rasp_poc` C++; OpenVINO/ONNX, CPU).

---

## 0. Guiding principles

1. **Integrate into vizor_nvr** (not ai_scenarios/ or vizor-gpu/ai_workers). Those
   are separate frameworks — borrow models/learnings only.
2. **POC logic is framework-agnostic and proven** — port the state machines /
   voting cores almost verbatim; do NOT re-derive them.
3. **CPU → GPU/Triton** exactly as FRS/SS were done: plugin becomes a thin Triton
   client, models served by the shared Triton, per-camera workers pull frames via
   go2rtc + NVDEC.
4. **Reuse the SDK** (`scenarios/_sdk/vizor_sdk`): `TritonClient`, `FramePuller`
   (NVDEC), `ByteTracker`, `rules` (Zone/Line/Dwell), `NvrClient`, `record_event`
   pattern, `build_app`.
5. **UI/UX consistency** across all AI scenarios is a first-class deliverable.

---

## 1. PPE — flow + integration

### 1.1 PPE POC flow (what we're porting)

```
frame ─► YOLO26n detect (person + helmet/vest)
      ─► ByteTrack (person) + occlusion re-linking (StableIdMapper)
      ─► body-zone PPE→person assignment (associate_ppe)
      ─► EvidenceSmoother  (PPE present only if seen ≥3 of last 8 frames)
      ─► [optional] DINOv2 ViT verifier (helmet veto <0.58 / rescue ≥0.82; vest rescue-only)
      ─► ComplianceEngine state machine:
            present → clear; absent > missing_grace(1s) & eligible → violation
            min_present(3s) before "ever_seen"; cooldown(30s) per person
            emits PPE_MISSING / PPE_REMOVED
      ─► alert + annotated snapshot
```

The sophistication that kills false alerts (the whole value): **temporal grace +
smoothing + occlusion re-linking + body-zone assignment + DINOv2 verifier.**

### 1.2 Models

| Model | What | Serving |
|-------|------|---------|
| `best.pt` (YOLO26n, 11 classes; 3 used: Person, helmet, vest, no_helmet) | person + PPE detector | export to ONNX → Triton `ppe_yolo26` |
| DINOv2-small backbone + tiny linear heads (`vit_ppe_dinov2_small.npz`) | helmet/vest second-stage verifier | DINOv2 → Triton `dinov2_small`; the .npz linear heads (trivial numpy) stay client-side |

Note: model is AGPL (Ultralytics) — confirm licensing for resale.

### 1.3 What ports as-is vs reworks

**Port nearly verbatim into the plugin worker** (pure Python, framework-agnostic):
- `ComplianceEngine` (state machine — the crown jewel)
- `EvidenceSmoother` (3/8 temporal smoothing)
- `StableIdMapper` (occlusion re-linking) — OR fold into the SDK `ByteTracker`
- `associate_ppe` / `point_in_zone` (body-zone assignment), `deduplicate_persons`,
  `eligible_people`, ROI helpers
- Alert schema → maps to the standard scenario event

**Rework:**
- Detection: replace in-process `YOLO(best.pt)` ×2 with **SDK `TritonClient`** calls
  (person-track + PPE-detect). NMS/decode client-side.
- DINOv2 verifier: host backbone on Triton; keep .npz heads client-side.
- Per-camera workers via SDK `FramePuller` (go2rtc + NVDEC), not the POC's
  `LatestFrameCapture`.
- Events: persist to the PPE plugin DB + emit via `record_event`-style path (see §1.4).
- Config: POC's ~40 CLI args → manifest `camera_config_schema` (required PPE list,
  ROI polygon, thresholds, grace/cooldown).
- Snapshots: async to plugin store, not synchronous `cv2.imwrite`.

### 1.4 The Events-tab bug (must fix as part of PPE)

**Root cause:** `frontend/src/pages/ai/tabs/EventsTab.js` is **FRS-hardcoded** —
imports `listFrsEvents`, hits `/api/ai/frs/events`, renders FRS columns (FACE /
MATCH / person + confidence) and `frsShared`. PPE's `events` tab reuses this same
component, so it shows FRS data (or "No recognition events").

Also: the vizor_nvr **PPE plugin has no persistent events store** — `app.py` only
returns per-video-job in-memory events. Live PPE violations aren't persisted.

**Fix (two parts):**
1. **Backend**: PPE plugin needs a real events table + a `/events` list endpoint
   (paginated, PPE-shaped: time, camera, violation type, worker/track id, missing
   PPE items, confidence, snapshot, bbox) + live workers that write violations via
   the shared `record_event` pattern.
2. **Frontend**: make `EventsTab` **scenario-generic** — drive columns/labels/event
   types from the scenario manifest (`event_types`) instead of FRS constants, and
   call `/api/ai/<slug>/proxy/events`. FRS keeps its face columns; PPE shows
   violation columns; ANPR shows plate columns. One generic component, manifest-driven.

### 1.5 PPE tabs (manifest already declares)

`cameras · live · ppe_detect (Detect) · events · reports · settings` — keep, but
Events + Reports must render PPE data, not FRS.

---

## 2. ANPR — flow + integration + Milesight-parity scope

### 2.1 ANPR POC flow (what we're porting)

```
frame ─► YOLO26s plate detect (single "plate" class, letterboxed)
      ─► crop plate ─► PP-OCRv6 recognition (CTC greedy decode)
      ─► gate: det conf ≥0.6, plate width ≥min, ROI, OCR conf ≥thresh, PLATE_REGEX match
      ─► VehicleSession voting (accumulate reads; on exit, vote:
             most-common length → per-position char majority; ≥3 reads)
      ─► emit ONE plate_read event (voted plate + mean conf + best crop)
```

India-targeted: plate regex hardcoded (`MH12AB1234` + BH-series). OCR is **stock
PP-OCRv6, NOT fine-tuned** (~48% exact / 70% char) — fine-tune on Indian plates is
the #1 accuracy lever (accumulated crops = training data).

### 2.2 CPU → GPU/Triton conversion (the explicit ask)

Mirror FRS/SS: plugin = thin Triton client.

| POC (CPU) | vizor_nvr (GPU/Triton) |
|-----------|------------------------|
| OpenVINO/ONNX plate detect in-process | Triton `anpr_plate_detector` (prefer the rasp NMS-baked ONNX export) |
| OpenVINO/ONNX PP-OCRv6 in-process | Triton `ppocr_v6_rec` (dynamic width axis) |
| `LatestFrame` / `FFmpegReader` | SDK `FramePuller` (go2rtc + NVDEC) |
| single global session (single-lane!) | SDK `ByteTracker` per-vehicle → vote PER TRACK (fixes multi-vehicle collapse) |
| SQLite + Flask dashboard | plugin DB + NVR event emission + AI-module UI |

**Critical rework:** the POC has **no real tracker** (single-lane assumption — two
plates collapse into one). Use the SDK `ByteTracker` to assign vehicle track ids,
run the voting core **per track**. This is mandatory for real multi-lane sites.

### 2.3 Milesight-parity — new functionality (market demand)

Reference: milesight.com/security/product/anpr-cameras. Beyond plate read:

| Feature | How (in vizor_nvr) |
|---------|--------------------|
| **Vehicle type** | a vehicle classifier (car/truck/bus/bike/auto) — new Triton model OR reuse yolo26 vehicle classes; attach `vehicle_type` to the plate event |
| **Direction** | from the SDK `ByteTracker` track history — entry/exit vector across a line (SDK `LineCrossCounter` already does line-cross); emit `direction: in/out` |
| **Speed** | track displacement / time across a calibrated line pair or perspective scale; operator sets the real-world distance (config) → km/h. Honest flag: single-camera speed is an **estimate**, needs per-camera calibration; document accuracy limits |
| **Whitelist / Blacklist** | plate lists per scenario (DB table: plate, list_type, label, valid_from/to). On each `plate_read`, match → tag event `list_hit: whitelist/blacklist` + raise a **blacklist alert** (high severity) / allow-action for whitelist. Operator UI to manage lists (add/import CSV/delete) |
| **Region-configurable plate format** | move the hardcoded India regex to per-scenario config (`plate_format`, default India + BH); other regions selectable |

### 2.4 ANPR tabs (proposed, consistent with FRS/PPE)

`cameras · live · plates (Detect/Search) · whitelist-blacklist · events · reports
· settings`

---

## 3. UI/UX consistency (cross-scenario deliverable)

Audit + unify so every AI scenario feels identical:
- **Generic Events tab** (manifest-driven columns) — fixes the PPE-shows-FRS bug
  and serves ANPR too.
- **Generic Reports tab** — currently FRS-shaped; drive metrics from the scenario.
- Consistent tab set, header (back button ✓ done), empty states, snapshot viewer,
  filters, pagination envelope (already unified backend-side).
- Shared scenario shells/components in `pages/ai/tabs/` parameterised by slug +
  manifest, not per-scenario forks.

---

## 4. Proposed build order (parallel-friendly)

Once scope is approved, work splits into parallel tracks:

**Track A — PPE backend**: Triton models (YOLO26 + DINOv2 export), PPE plugin
worker (port ComplianceEngine/Smoother/StableIdMapper/associate_ppe), events table
+ `/events` endpoint, live per-camera workers, manifest config.

**Track B — ANPR backend**: Triton models (plate detect + PP-OCRv6), ANPR plugin
on SDK, ByteTracker per-vehicle voting, events table, whitelist/blacklist DB +
endpoints, vehicle-type/direction/speed, region-config.

**Track C — Shared UI**: generic manifest-driven Events + Reports tabs (fixes the
FRS-data bug), PPE Detect tab, ANPR Plates + Whitelist/Blacklist tabs, consistency
pass.

**Track D — Models/validation**: export + register models on Triton; PPE on real
footage; ANPR plate accuracy + (stretch) PP-OCRv6 Indian fine-tune.

Dependencies: C depends on A/B event shapes; D feeds A/B. A and B are independent.

---

## 5. Decisions (LOCKED)

1. **PPE events store** → **Plugin DB + NVR emit (FRS-style).** PPE plugin gets its
   own Postgres (like FRS) for violations + emits to the NVR events module.
2. **Vehicle-type** → **Reuse yolo26 vehicle classes** (car/truck/bus/bike). No new
   classifier model; derive `vehicle_type` from the existing detector.
3. **Whitelist/Blacklist** → **Per-scenario global** (one list applies across all
   ANPR cameras). DB: plate, list_type, label, valid_from/to + CSV import.
4. **PP-OCRv6 fine-tune** → **Ship stock first** (~48% exact), pipeline live;
   Indian fine-tune is a later accuracy boost (web_crops = training data).
5. **Speed calibration** → per-camera line + real-world distance entry; "estimate"
   accuracy framing documented (single-camera speed is approximate).
