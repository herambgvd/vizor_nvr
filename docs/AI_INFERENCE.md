# AI Inference — architecture, tuning, GPU profiles

How the AI scenarios (FRS, Suspect Search, PPE) run inference, and how to size
it for a given GPU. Read alongside [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)
(64-cam capacity is not yet load-validated).

## Architecture

```
camera (RTSP) ──go2rtc restream──► plugin worker ──HTTP──► Triton ──► GPU
                                   (per camera)            (shared)    (models)
```

- **Plugins are thin Triton clients.** FRS / SS / PPE run no in-process GPU work
  in production (`INFERENCE_BACKEND=triton`). They decode frames (NVDEC when
  `FRS_HWACCEL=cuda`), POST tensors to Triton over HTTP, and post-process.
- **Triton is the single GPU owner.** One `gvd_ai_triton` container serves all 7
  ONNX models to every plugin. Dynamic batching coalesces requests from many
  cameras into GPU batches — the throughput win at scale.
- **One worker per camera, one event loop per plugin.** The GIL is a non-issue:
  decode is in ffmpeg (C), inference is in Triton (separate process), so Python
  only marshals tensors.

## Models served by Triton

| Model | max_batch | instances | dynamic batch | Used by |
|-------|-----------|-----------|---------------|---------|
| `scrfd_10g` (face detect) | 0¹ | 4 | no¹ | FRS |
| `arcface_r50` (face embed) | 16 | 2 | yes (4,8,16) | FRS |
| `fairface` (age/gender/race) | 32 | 1 | yes | FRS, SS |
| `antispoofing` (liveness) | 32 | 1 | yes | FRS |
| `yolo26` (person/object det) | 0¹ | 1 | no¹ | SS, PPE |
| `person_reid` (ReID embed) | 32 | 1 | yes | SS |
| `clothing_yolos` (garment) | 0¹ | 1 | no¹ | SS |

¹ Detectors run `max_batch_size: 0` — input is shape-fixed (640) and one frame
per camera at a time, so per-request execution + multiple `instance_group`
copies parallelise better than batching variable-row detector outputs. The
embedders (ArcFace/FairFace/ReID) are the batchable hot path and carry dynamic
batching.

## GPU profiles — sizing `instance_group` count

Instance counts live in each `triton/model_repository/<model>/config.pbtxt`.
More instances = more concurrent copies of a model on the GPU = more parallelism,
at the cost of VRAM. Tune to the deployment GPU, then restart Triton.

| GPU (VRAM) | Cameras | SCRFD inst | ArcFace inst | Notes |
|------------|---------|-----------|--------------|-------|
| Laptop RTX 4060/4070 (8 GB) | ≤8 | 2 | 1 | Dev / small site. Lower instance counts to fit VRAM. |
| RTX 5070 (12 GB) | ~16–32† | 4 | 2 | Current committed default. †Monday load-test will set the real number. |
| A6000 / L40S (48 GB) | 64+† | 6–8 | 3–4 | Raise instances; plenty of VRAM headroom. |

† Channel counts are estimates until the load test runs — see KNOWN_LIMITATIONS.

To change: edit the `count:` under `instance_group` in the model's `config.pbtxt`,
then `docker compose ... restart triton`. Watch VRAM with `nvidia-smi`; back off
if you hit OOM at model load.

## Per-camera tuning (plugin env)

The proven-accurate FRS defaults are in `scenarios/frs/config/settings.py` and
should not be lowered platform-wide (looser gates pollute recognition). Scale
knobs that matter under load:

| Env | Default | Effect |
|-----|---------|--------|
| `FRS_HWACCEL` | `none` | Set `cuda` in production — NVDEC decode is essential past ~16 cameras (software decode saturates CPU). |
| `FRS_LIVE_FPS` | `5` | Analysed frames/sec per camera. Lower to cut GPU load; raises latency-to-detect. |
| `FRS_LIVE_VOTE_MIN_FRAMES` | `5` | Frames of consensus before an event. Do not lower — single-frame firing flickers. |
| `INFERENCE_BACKEND` | `onnxruntime-gpu` | Set `triton` in production for shared, batched inference. `onnxruntime` only for a single-node dev box. |

## What's already optimised vs pending

**Done** (64-cam hardening sprint): NVDEC GPU decode, Triton shared inference,
ArcFace dynamic-batch re-export, SCRFD ×4 instances, per-camera backpressure,
stall watchdog, memory/thread/fd leak guards, retention sweeper.

**Pending** (needs real load data — Monday): final batch-size / instance-count
tuning, measured channel capacity per GPU, 24-hour soak. Until then, the table
numbers are conservative estimates, not guarantees.
