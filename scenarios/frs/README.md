# FRS scenario plugin

Standalone face-recognition microservice for Vizor NVR. Detect → recognize →
track enrolled faces, with a person gallery, photo enrollment, forensic
investigate, transit, attendance and reporting. Runs as its own container,
self-registers its manifest with the NVR, and is reached only through the NVR's
licensed scenario proxy (`/api/ai/scenarios/frs/proxy/...`).

The NVR core holds **no** FRS state. This plugin owns everything:

| Concern        | Store                                    |
| -------------- | ---------------------------------------- |
| Gallery + events | own Postgres (`frs-db`)                |
| Face vectors   | own Qdrant collection (`vizor_frs_faces`) |
| Photo bytes    | own volume (`frs_photos` → `/data/frs`)  |
| Inference      | in-process onnxruntime-gpu (SCRFD + ArcFace) |

## Layout

```
scenarios/frs/
  app.py            FastAPI app — mounts routers, startup lifecycle. Thin.
  config.py         All env-bound settings + thresholds.
  db.py             Engine / session / table bootstrap (own Postgres).
  models.py         SQLAlchemy models (groups, persons, photos, attendance,
                    events, transit rules/sessions).
  schemas.py        Row → wire-dict serializers + datetime helpers.
  qdrant_store.py   Qdrant client + upsert / search / filtered-delete.
  recognition.py    OnnxEngine singleton + embed / detect / recognize / augment.
  registration.py   Manifest self-registration on boot.
  deps.py           Shared router deps (service-token auth, person recount).
  routers/
    health.py       /health, /health/deep
    groups.py       /groups CRUD
    persons.py      /persons CRUD
    photos.py       /persons/{id}/photos (enroll), /photos/{id}, image
    recognize.py    /recognize-image, /detect-faces, /snapshot
    investigate.py  /investigate, /tour/timeline/{person_id}
    transit.py      /transit/rules, /transit/sessions
    video_jobs.py   /video-jobs (async recognition over recordings/uploads)
    reports.py      /events, /attendance, /attendance/report, /reports/summary, /live
  inference/        Ported vizor-gpu pipeline (pure numpy/OpenCV + onnxruntime):
    scrfd.py        SCRFD detector preprocess + anchor decode + NMS.
    align.py        5-point affine → 112×112 ArcFace template.
    preprocess.py   ArcFace / antispoof pre/post-processing.
    quality.py      Sharpness, pose, geometry quality gates.
    enhance.py      Crop enhancement (pad/resize/denoise/sharpen).
    augment.py      Photometric augmentation for enrollment recall.
    engine.py       OnnxEngine — local ort.InferenceSession per model.
  scenario.json     Manifest (license_feature, proxy_routes, tabs, schema).
  Dockerfile  requirements.txt
```

## Models & serving

**Serving: in-process onnxruntime-gpu.** The plugin loads the ONNX models
directly with `onnxruntime` (CUDA execution provider) — no Triton, no gRPC hop.
For a single-node NVR this is the lowest-latency, lowest-ops option. (Triton
only pays off for multi-GPU-host fan-out, cross-scenario batching or model
versioning — overkill here.)

**Models used** (the same ONNX files Triton served in vizor-gpu):

| File                  | Role                     | Required | Input        |
| --------------------- | ------------------------ | -------- | ------------ |
| `scrfd_10g.onnx`      | Face detector (SCRFD)    | yes      | 1×3×640×640  |
| `arcface_r50.onnx`    | 512-d embedder (ArcFace) | yes      | 1×3×112×112  |
| `antispoofing.onnx`   | Liveness (MiniFASNet)    | no       | 1×3×80×80    |

Models are **not** committed to git (large binaries — see `.gitignore`). Load
them once into `./models` (bind-mounted read-only into the container):

```bash
# from a hosted store
FRS_MODEL_BASE_URL=https://models.internal/frs ./scripts/fetch-frs-models.sh
# or copy from a local Triton export dir
FRS_MODEL_SRC_DIR=/var/lib/vizor/triton-models ./scripts/fetch-frs-models.sh
```

Then restart the plugin:

```bash
docker compose -f docker-compose.yml -f docker-compose.ai.yml up -d frs
```

**Graceful fallback.** With the models absent the plugin still runs: a
deterministic 512-d color-histogram embedding stands in for ArcFace so the full
gallery / enroll / recognize API works end to end. `GET /health/deep` reports
`onnx.ready=false` in that state. Drop the model files in and it flips to the
real ArcFace pipeline — **no code or config change**.

Thresholds (overridable via env): match cosine `FRS_SIMILARITY=0.6`, duplicate
`FRS_DUP_COSINE=0.92`, enroll gates `FRS_MIN_FACE_PX=80` / `FRS_MAX_POSE_DEG=45`
/ `FRS_MIN_SHARPNESS=50`.
