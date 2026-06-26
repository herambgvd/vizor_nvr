# SMCC client deploy — Vizor NVR (FRS ×4 + PPE ×7)

No code ships. Only Docker **images** (via Google Drive) + a signed **license** + the
compose/env files. The client runs everything from prebuilt images.

Client machine (verified):
- NVIDIA RTX 2000 Ada, 16 GB, driver 580 / CUDA 13.0 → compatible (our images are
  CUDA 12.5; the driver is backward-compatible). Compute cap sm_89.
- An OLD POC stack (`registry.digitalocean.com/gvd-registry/vizor/*:2.0.5`, ollama,
  old triton, mongo) is running — **remove it first** (step 0).

--------------------------------------------------------------------------------
## 0. On the client — stop + remove the old POC stack

```bash
# stop + remove ALL the old POC containers
docker rm -f vizor-frontend vizor-backend vizor-tasks vizor-triton vizor-mongo \
  vizor-redis vizor-qdrant vizor-ollama vizor-rustfs vizor-frs-worker \
  vizor-ppe-worker vizor-go2rtc 2>/dev/null

# remove the old CUSTOM images (DO registry) + the POC-only big ones.
docker image rm -f $(docker images 'registry.digitalocean.com/gvd-registry/*' -q) 2>/dev/null
docker image rm -f ollama/ollama:latest mongo:7 2>/dev/null

# KEEP these — we reuse them, so we DON'T ship them (saves Drive space):
#   redis:7-alpine, rustfs/rustfs:latest, nvidia/cuda:12.4.1-base-ubuntu22.04
# The client's qdrant:latest + go2rtc:1.9.4 are REPLACED by the pinned versions we
# ship (qdrant v1.18.0, go2rtc 1.9.9) — remove the old ones:
docker image rm -f qdrant/qdrant:latest alexxit/go2rtc:1.9.4 2>/dev/null

docker volume prune -f      # ONLY if the client confirms the POC data is disposable
```

Keep the host's NVIDIA driver + docker + nvidia-container-toolkit (already installed),
and the reusable base images above.

--------------------------------------------------------------------------------
## 1. On YOUR machine — build the images (with the license fix)

```bash
cd /home/gvd-ai/office/clarify/vizor_nvr
# build all custom images
docker compose -f docker-compose.yml -f docker-compose.ai-base.yml \
  -f docker-compose.frs.yml -f docker-compose.ppe.yml build \
  backend frontend migrate frs ppe
```

Custom images produced: `vizor_nvr-backend`, `vizor_nvr-frontend`,
`vizor_nvr-migrate`, `vizor_nvr-frs`, `vizor_nvr-ppe`.

Base images to also transfer (the client doesn't have them):
`nvcr.io/nvidia/tritonserver:24.08-py3`, `timescale/timescaledb:2.17.2-pg16`,
`postgres:16-alpine`, `redis:7-alpine`, `qdrant/qdrant:v1.18.0`,
`alexxit/go2rtc:1.9.9`, `nginx:1.27-alpine`, `rustfs/rustfs:latest`.

--------------------------------------------------------------------------------
## 2. On YOUR machine — pack images for Google Drive

Run `scripts/pack_images.sh` (below). It `docker save | gzip`s each image into
`./_ship/`. Triton is ~11 GB compressed — split if Drive struggles.

Upload `_ship/*.tar.gz` + the whole repo's `triton/model_repository/` (ONNX models,
NOT the `*_trt/1/*.plan` files — those are GPU-specific, rebuilt on the client) + the
compose files + `.env` to Google Drive.

--------------------------------------------------------------------------------
## 3. On the client — load the images + repo

```bash
mkdir -p ~/vizor && cd ~/vizor
# copy the Drive download here: _ship/, docker-compose*.yml, .env, triton/, scenarios/ (only the manifests it needs)
for f in _ship/*.tar.gz; do echo "load $f"; gunzip -c "$f" | docker load; done
docker images | grep -E 'vizor_nvr|triton|timescale'   # sanity
```

--------------------------------------------------------------------------------
## 4. On the client — rebuild the TensorRT engines for THIS GPU

The `*_trt/1/model.plan` files are GPU-model + TRT-version specific, so they are NOT
shipped. Rebuild them from the shipped ONNX models on the client's RTX 2000 Ada:

```bash
cd ~/vizor
# build_trt_engines.sh runs trtexec inside the triton container for every model that
# has an ONNX source. It only needs to run ONCE on the client.
bash triton/build_trt_engines.sh
```

FRS needs: scrfd_10g, arcface_r50, fairface, antispoofing.
PPE needs: ppe_yolo26, siglip_ppe (+ the DALI ensemble `ppe_yolo_pp` / `ppe_yolo_ensemble`,
which are not TRT and ship as-is).

--------------------------------------------------------------------------------
## 5. Issue the license (FRS=4, PPE=7) bound to the client machine

```bash
# (a) On the client, get the hardware fingerprint AFTER the backend is up once:
curl -s http://localhost:8000/api/license/fingerprint
#   → returns a 64-char hex string. Send it to you.

# (b) On YOUR machine, sign the license:
python scripts/sign_license.py sign \
  --private-key vendor-keys/smcc/private.pem \
  --customer "SMCC" \
  --license-id "SMCC-2026-001" \
  --expires "2027-06-30" \
  --tier business \
  --camera-limit 16 \
  --scenarios frs,ppe \
  --feature-limits '{"frs":4,"ppe":7}' \
  --features recording,playback,attendance,investigation \
  --hardware-fingerprint "<the 64-char value from step a>" \
  --out smcc-2026.lic
```

`--feature-limits '{"frs":4,"ppe":7}'` is the per-scenario cap (new). `--camera-limit`
is the NVR (non-AI) channel cap — set to the total NVR cameras they bought.

(c) On the client: Settings → License → upload `smcc-2026.lic`.

--------------------------------------------------------------------------------
## 6. On the client — bring up the stack

```bash
cd ~/vizor
# core + ai-base + FRS + PPE (worker-v2 workers auto-start, no profile)
docker compose -f docker-compose.yml -f docker-compose.ai-base.yml \
  -f docker-compose.frs.yml -f docker-compose.ppe.yml up -d
```

Then: enable FRS on up to 4 cameras, PPE on up to 7 (the license enforces these caps —
the UI blocks the 5th FRS / 8th PPE camera).

--------------------------------------------------------------------------------
## Notes / gotchas
- GPU budget on 16 GB: Triton (FRS scrfd+arcface+fairface+antispoof ~2 GB) + PPE
  (yolo+siglip+dali ~1.5 GB) + decode. Comfortable on 16 GB.
- PPE worker-v2 + FRS worker-v2 are NORMAL services now (no `--profile`); they come up
  with `up -d` and after a reboot. (FRS_WORKER_V2 / PPE_WORKER_V2 hardcoded on.)
- PPE GPU preprocess (DALI ensemble) + ffmpeg decode are default-on; CPU stays low.
- After a host reboot the whole stack auto-restarts (`restart: unless-stopped`).
