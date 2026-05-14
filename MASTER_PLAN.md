# Vizor Video Intelligence Platform — Master Build Plan

> **Mission:** Build enterprise-grade Video Intelligence + NVR platform on NVIDIA Metropolis Microservices. Compete with BriefCam, Avigilon ACC, Genetec Security Center. AI-native, microservices-first. India price advantage, Western AI sophistication.

> **Positioning:** NOT just an NVR. Complete VAaaS (Video Analytics as a Service) with recording. Recording is one feature; analytics is the product.

> **Architecture:** NVIDIA Metropolis Microservices = compute plane. Vizor backend = control plane + business logic. Vizor React = UX layer. All NVIDIA stack components are FREE under NVIDIA EULA.

> **End state (10-12 months):** Single product `vizor_nvr` consuming Metropolis Microservices (VST, Perception, MTMC, Behavior Analytics, Event, Visual Search, Spatial Intelligence). `vizor-app` and `vizor-gpu` deleted. Multi-cam sync, SSO, LPR, federation, HA, mobile apps, 5 vertical packs.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  CAMERAS (RTSP/ONVIF, H.264/H.265)                                   │
└─────────┬────────────────────────────────────────────────────────────┘
          │
   ┌──────▼──────────────────────────────────────────────────────────┐
   │  NVIDIA VST (Video Storage Toolkit)                             │
   │  - RTSP ingest, recording (fmp4), HLS playback, segment index   │
   │  - REST API for playback control                                │
   └──┬─────────────────────────┬──────────────────────────────────┘
      │ raw stream              │ recorded segments → RustFS / S3
      │                         │
   ┌──▼─────────────────────────▼──────────────────────────────────┐
   │  Perception Microservice (DeepStream-based)                   │
   │  - Composite pipeline: detect → track → classify → analyze    │
   │  - Configurable per camera                                    │
   │  - Uses NGC pretrained models + custom Triton models          │
   └──┬────────────────────────────────────────────────────────────┘
      │ detection events via nvmsgbroker (Redis/Kafka)
      │
   ┌──▼──────────────────────────────────────────────────────────────┐
   │  Metropolis Microservices Bundle                                │
   │  - MTMC Tracker (cross-cam person tracking)                     │
   │  - Behavior Analytics (zones, lines, dwell, occupancy)          │
   │  - Event Microservice (aggregation, fan-out)                    │
   │  - Visual Search (Milvus + CLIP, or our Qdrant w/ adapter)     │
   │  - Analytics (heatmap, count, trend)                            │
   │  - Spatial Intelligence (floor plan, multi-floor)               │
   │  - MMJ (LLM Q&A on video, optional)                             │
   └──┬──────────────────────────────────────────────────────────────┘
      │ structured events + metadata
      │
   ┌──▼──────────────────────────────────────────────────────────────┐
   │  Vizor NVR Backend (FastAPI) — CONTROL PLANE                    │
   │  - Adapter layer to Metropolis APIs (REST/gRPC)                 │
   │  - Event ingest endpoint /api/events/ingest                     │
   │  - Business logic: rules engine, alarm workflow, FRS persons,   │
   │    investigations, model registry, webhook out, billing         │
   │  - Auth (JWT/RBAC/2FA/audit)                                    │
   │  - Federation controller across multi-NVR clusters              │
   │  - Postgres + TimescaleDB for non-Metropolis data               │
   └──┬──────────────────────────────────────────────────────────────┘
      │ JSON REST + WebSocket
      │
   ┌──▼──────────────────────────────────────────────────────────────┐
   │  Vizor React Frontend — UX LAYER                                │
   │  - Camera mgmt, live grid (go2rtc WebRTC for low latency)       │
   │  - Scrub timeline (VST playback) w/ AI markers                  │
   │  - FRS, investigations, search, alarms                          │
   │  - Dashboards (Metropolis Analytics)                            │
   │  - Customer branding, vertical packs                            │
   └─────────────────────────────────────────────────────────────────┘
```

---

## Repos & Service Topology (Final State)

```
vizor_nvr/                 PRIMARY PRODUCT
  ├── backend/             FastAPI control plane + adapters
  ├── frontend/            React UX
  ├── metropolis/          Deployment configs for Metropolis services
  │   ├── vst/             VST config files (per-camera streams)
  │   ├── perception/      DeepStream pipeline configs (PGIE, SGIE, tracker)
  │   ├── analytics/       Behavior Analytics zone/line configs
  │   ├── mtmc/            Multi-Target Multi-Camera tracker config
  │   ├── visual-search/   Visual Search Microservice config
  │   ├── event/           Event Microservice config
  │   └── compose.yml      Compose stack for all Metropolis services
  ├── tao/                 TAO Toolkit training scripts (custom PPE, FRS, anomaly)
  ├── ngc-models/          Pinned NGC pretrained model versions + checksums
  └── docker-compose.yml   Top-level orchestration

vizor-app/                 DELETED Phase 1.9
vizor-gpu/                 DELETED Phase 2.x (replaced by Perception)
```

External services run in same Docker network: `postgres+timescaledb`, `redis`, `go2rtc` (WebRTC only), `triton`, `qdrant`, `rustfs`, plus all Metropolis Microservices.

---

## Decisions Locked

| # | Decision | Choice |
|---|---|---|
| 1 | Database | Postgres + TimescaleDB single instance. Mongo dies |
| 2 | Live WebRTC | go2rtc only (better than VST WebRTC) |
| 3 | Recording | **NVIDIA VST** (replaces go2rtc recording + MediaMTX) |
| 4 | Analytics | **NVIDIA Perception Microservice** (DeepStream). Python workers die |
| 5 | Cross-cam tracking | **MTMC Microservice** (replaces custom investigation logic) |
| 6 | Zone/line/dwell/occupancy | **Behavior Analytics Microservice** |
| 7 | Semantic search | **Visual Search Microservice** OR keep Qdrant w/ adapter |
| 8 | Heatmap/count/trend | **Analytics Microservice** |
| 9 | Floor plan / spatial | **Spatial Intelligence Microservice** |
| 10 | LLM Q&A | **MMJ Microservice** (replaces Ollama Copilot) |
| 11 | Frontend | Vizor React (NOT Metropolis reference UI) |
| 12 | Backend | Vizor FastAPI (adapter + business logic) |
| 13 | Tenancy | Single-tenant per Vizor install. Federation handles multi-site |
| 14 | Auth | NVR JWT + 2FA + RBAC. API key for m2m. SSO Phase 2 |
| 15 | Vector search | Qdrant (Phase 1). Adapter to Visual Search Phase 2 |
| 16 | Triton | Stays. Perception Microservice calls Triton via nvinferserver |
| 17 | Codec | H.264 mandatory. H.265 supported, transcoded for WebRTC |
| 18 | Retention | 14 days raw, 90 days events. Per-camera override |
| 19 | Secrets | SOPS for file-based, K8s secrets if k8s deploy |
| 20 | Observability | Prometheus + Grafana + OpenTelemetry (LGTM stack) |
| 21 | Deploy | Docker Compose first. K8s manifests already exist |
| 22 | CI/CD | GitHub Actions. Image push to GHCR |
| 23 | Models | NVIDIA NGC pretrained models primary. TAO fine-tuning for customer data |
| 24 | NVIDIA Inception | OPTIONAL — skipped. All software free under EULA without it. Apply later if free DGX credits needed |
| 25 | DeepStream version | DS 7.1 LTS (Perception Microservice handles upgrade for us) |

---

## What Survives From Existing Code

| Existing | Decision |
|---|---|
| `vizor_nvr/backend/app/auth/` (JWT, RBAC, 2FA, audit) | **KEEP.** Metropolis doesn't replace |
| `vizor_nvr/backend/app/cameras/` (CRUD, ONVIF, PTZ) | **KEEP.** Customer-facing |
| `vizor_nvr/backend/app/auth/api_keys.py` | **KEEP.** Used by Metropolis → NVR ingest |
| `vizor_nvr/backend/app/events/ingest_router.py` | **KEEP.** Adapter target for Metropolis events |
| `vizor_nvr/backend/app/recordings/` | **REWIRE.** Calls VST API instead of ffmpeg |
| `vizor_nvr/backend/app/bookmarks/` | **KEEP.** Business logic |
| `vizor_nvr/backend/app/storage/` | **KEEP** (used by VST as storage backend) |
| `vizor_nvr/backend/app/monitoring/` | **KEEP** + extend with Metropolis service health |
| `vizor_nvr/backend/app/settings/` | **KEEP.** App settings |
| `vizor_nvr/backend/app/notifications/` | **KEEP.** Channel mgmt |
| `vizor_nvr/backend/app/audit/` | **KEEP.** Compliance log |
| `vizor_nvr/frontend/` | **KEEP** + add Metropolis-driven screens |
| `vizor_nvr/backend/app/services/ffmpeg_manager.py` | **DELETE.** VST replaces |
| `vizor_nvr/backend/app/services/go2rtc_manager.py` | **KEEP** (WebRTC live only) |
| Python `vizor-gpu/ai_workers/*` | **DELETE.** Perception replaces |
| `vizor-app/` entire | **DELETE** (Phase 1.9 cutover) |
| Mongo (vizor-app data) | **MIGRATE** to Postgres + Qdrant, then delete |
| MediaMTX | **DELETE.** VST replaces |
| ARQ webhook delivery | **KEEP Phase 1.** Evaluate Event Microservice Phase 2 |

**Net code reduction: ~60-70% across the workspace.**

---

# Phase 1 — Foundation + First Metropolis Pilot (Weeks 1-12)

**Goal:** Stable Vizor NVR foundation, NVIDIA Inception accepted, VST + Perception Microservice running on dev node with one camera. First Python worker (FRS) replaced by Perception pipeline. Adapter layer proven end-to-end.

**Exit criteria:**
- **FRS scenario shipping** (Metropolis Perception + ArcFace via Triton)
- **People Counting & Occupancy scenario shipping** (Behavior Analytics + PeopleNet)
- AI Scenarios catalog API live with full Metropolis-offered roadmap (28 scenarios listed, 2 GA, rest planned)
- Per-camera scenario config UI works
- NGC pretrained models pinned + downloaded (PeopleNet, FaceDetect, ArcFace minimum)
- VST recording one camera, events visible in NVR via /api/events/ingest
- Behavior Analytics Microservice deployed alongside Perception
- Python FRS + People Mgmt workers decommissioned
- Mongo decommissioned, single Postgres+TimescaleDB
- MediaMTX decommissioned
- CI green, observability live, SOPS secrets
- vizor-app archived

## Phase 1 Detailed Tasks

### 1.1 Pre-flight ✅ DONE
- [x] Tag baselines: `git tag pre-absorb-baseline` on all 3 repos
- [x] Disk cleanup (47GB reclaimed)
- [x] Pre-flight checks passed

### 1.2 NVR Foundations ✅ DONE
- [x] API keys table + middleware (m2m auth)
- [x] Events table extended for AI metadata
- [x] `/api/events/ingest` batch endpoint w/ idempotency
- [x] Prometheus `/metrics` endpoint + custom metrics module
- [x] Alembic migration `phase8_ai_foundations`
- [x] Alembic env wired to pick up new models

### 1.3 NVIDIA Inception + Environment Prep (Week 1-3)
- [ ] **NVIDIA Inception application** — OPTIONAL, skipped for now. Apply later if free DGX credits / co-marketing needed. All software (DeepStream, Metropolis, NGC models, TAO, Triton) is free under EULA without Inception
- [x] **NGC account** + API key for downloading pretrained models
- [ ] **DeepStream license verification** — accept NVIDIA EULA for redistributable bits
- [ ] **NGC pretrained model inventory** — pin versions + download:
  - PeopleNet (person/car/bag detection)
  - FaceDetectIR + FacialLandmarks (face pipeline)
  - LPDNet + LPRNet (license plate)
  - TrafficCamNet + VehicleType + VehicleMake + VehicleColor
  - ActionRecognitionNet
  - ReIDNet (cross-cam person re-ID)
  - BodyPose / PoseClassification
  - GazeEstimation / EmotionRecognition (optional)
  - PeopleSemanticSegmentation
- [ ] Storage: NGC models in `vizor_nvr/ngc-models/`, checksums recorded, never committed to git (~30 GB total)
- [x] **Dev GPU verified**: RTX 4050 6GB Laptop, driver 580.126, CUDA 13.0, nvidia-container-toolkit working
- [x] **Production GPU arriving Week 2**: RTX 5060 16GB. Sufficient for Phase 1 production validation (30-50 cams composite pipeline). Replaces dev RTX 4050.
  - Driver target: 580+
  - DeepStream 7.1 + CUDA 12.6 supported on Blackwell (5060)
  - Plan: continue Phase 1 software work on RTX 4050 this week, migrate to 5060 next week for Perception runtime tests

### 1.4 SOPS Secrets Vault (Week 2)
- [ ] Install SOPS + age
- [ ] Generate age key pair, store private key offline + 1Password
- [ ] `.sops.yaml` config in `vizor_nvr/`
- [ ] Encrypt `.env` → `.env.sops`
- [ ] Decryption hook in install script
- [ ] Rotate plaintext secrets after migration

### 1.5 TimescaleDB Extension (Week 2-3)
- [ ] Add TimescaleDB extension to Postgres compose
- [ ] Alembic migration `phase9_timescale`:
  - `SELECT create_hypertable('events', 'triggered_at', migrate_data => true)`
  - Compression policy: events compressed after 7 days
  - Retention policy: events kept 90 days
- [ ] Continuous aggregates: `events_5min`, `events_1h`, `events_1d` per (camera, detection_type, severity)
- [ ] Indexes on hypertable: `(camera_id, triggered_at)`, `(source_service, triggered_at)`

### 1.6 AI Schema — Persons, Models, Webhooks, Scenarios (Week 3-4)
Alembic migration `phase10_ai_schema`:
- [ ] `ai_scenarios` (id, slug, name, schema_version, description, default_config JSONB)
- [ ] `camera_ai_configs` (camera_id FK, scenario_id FK, config JSONB, enabled, updated_at)
- [ ] `frs_persons` (id, external_id, name, group_id FK, attributes JSONB, created_at)
- [ ] `frs_groups` (id, name, description, color)
- [ ] `frs_photos` (id, person_id FK, storage_key, qdrant_point_id, uploaded_at)
- [ ] `frs_investigations` (id, person_id FK, status, params JSONB, result JSONB, created_at)
- [ ] `frs_attendance` (person_id FK, camera_id FK, ts, type) — hypertable
- [ ] `vq_captions` (event_id FK, caption, qdrant_point_id, created_at) — hypertable
- [ ] `vq_attributes` (event_id FK, kind, value, confidence)
- [ ] `models` (id, name, version, manifest_json, signature, status, created_at, ngc_resource_id)
- [ ] `model_deployments` (model_id FK, scenario_id FK, active, deployed_at)
- [ ] `inference_jobs` (id, camera_id FK, start_ts, end_ts, model_id FK, status, result JSONB)
- [ ] `webhook_subscriptions` (id, url, events TEXT[], secret, enabled, created_at)
- [ ] `webhook_deliveries` (id, sub_id FK, payload JSONB, status, attempts, error, created_at) — hypertable
- [ ] `metropolis_services` (id, service_type, instance_url, health_status, last_check_at, version)

### 1.7 Vizor-App Data Migration to Postgres (Week 4-5)
Script: `vizor_nvr/backend/scripts/migrate_from_vizor_app.py`
- [ ] Mongo `persons` → `frs_persons`
- [ ] Mongo `person_photos` → `frs_photos` (preserve Qdrant point IDs)
- [ ] Mongo `groups` → `frs_groups`
- [ ] Mongo `investigation_jobs` → `frs_investigations`
- [ ] Mongo `detection_events` → NVR `events` (AI fields populated)
- [ ] Mongo `webhook_subscriptions` → `webhook_subscriptions`
- [ ] Mongo `webhook_deliveries` → `webhook_deliveries`
- [ ] Mongo `scenarios` → `ai_scenarios` + `camera_ai_configs`
- [ ] Mongo `models` → `models`
- [ ] Idempotent, dry-run flag, row-count parity validation, progress reporting

### 1.8 VST Stand-up (Week 5-6)
- [ ] VST Docker compose service (NVIDIA-provided image)
- [ ] Configure storage backend: RustFS S3 (or local volume Phase 1)
- [ ] Configure recording: fmp4 segments, 60-second duration, retention per camera config
- [ ] REST API endpoints documented:
  - `POST /vst/api/v1/streams` (add camera)
  - `GET /vst/api/v1/playback/{stream_id}?from=&to=` (HLS playback URL)
  - `GET /vst/api/v1/segments?stream_id=&from=&to=` (segment list)
  - `DELETE /vst/api/v1/streams/{stream_id}` (remove)
- [ ] NVR backend adapter: `app/services/vst_client.py` — async REST client
- [ ] On camera CRUD: backend syncs camera to VST
- [ ] Test: add camera, verify recording starts, segments visible in VST API, HLS playback works
- [ ] Document VST image version + checksum

### 1.9 Perception Microservice — First Pipeline (Week 6-8)
- [ ] Perception Microservice Docker compose service
- [ ] Build DeepStream config file for FRS:
  - `nvurisrcbin` source: pull from VST or directly camera RTSP
  - `nvstreammux` batching: batch_size=4 to start
  - PGIE: FaceDetectIR (NGC)
  - Tracker: NvDCF
  - SGIE: ArcFace via Triton `nvinferserver`
  - `nvmsgconv` → `nvmsgbroker` (Redis Stream output)
- [ ] Triton model_repository for ArcFace (already exists in vizor-gpu, copy)
- [ ] Validate: pipeline starts, sees face, emits to Redis Stream
- [ ] Document pipeline config file as template for future scenarios

### 1.10 Metropolis → NVR Bridge (Week 8-9)
- [ ] Bridge service: `vizor_nvr/backend/app/services/metropolis_bridge.py`
- [ ] Subscribes to Redis Stream output from nvmsgbroker
- [ ] Transforms Metropolis event schema → NVR event schema:
  - object class, bbox, track_id → detection_type, bbox, track_id
  - face embedding match → person_id (Qdrant lookup)
  - timestamp, camera id passthrough
- [ ] Computes dedup_key for idempotency
- [ ] Batches and POSTs to `/api/events/ingest` (m2m API key)
- [ ] Metrics: bridge throughput, latency, errors
- [ ] Runs as background task in NVR backend (or separate container if scale demands)

### 1.11 Frontend Integration (Week 9-10)
- [ ] Camera detail page: "AI Scenarios" tab with toggle (FRS / PPE / People / LPR placeholders)
- [ ] Timeline view: events overlay colored markers (face=blue, ppe=orange, vehicle=green, person=yellow)
- [ ] Filter chips on timeline: detection_type, source_service
- [ ] Click marker → event detail panel (snapshot, confidence, track_id, person_match if FRS)
- [ ] Investigation page: select person → search across cameras (Phase 1 via Postgres event query, MTMC later)
- [ ] Live view unchanged (go2rtc WebRTC)

### 1.12 Dual-Run + FRS Migration (Week 10-11)
- [ ] Both stacks run in parallel: Python FRS worker + Perception FRS pipeline on same camera
- [ ] Event reconciliation: count, person match accuracy, latency
- [ ] Accept if Perception >= Python on accuracy AND latency
- [ ] Feature flag `FRS_USE_PERCEPTION=true` switches frontend reads
- [ ] Monitor 7 days

### 1.13 Cutover + Decommission (Week 11-12)
- [ ] Stop Python FRS worker
- [ ] Archive `vizor-app/` to `git tag vizor-app-final`, then physically remove from `docker-compose.yml`
- [ ] Decommission MediaMTX
- [ ] Decommission Mongo (archive volume 90 days read-only)
- [ ] Update install scripts + customer-facing docs
- [ ] Update `vizor-gpu` to remove FRS worker (PPE, People, VQ remain for now)

### 1.14 Phase 1 Hardening (Week 12)
- [ ] DLQ replay tooling for failed event ingests
- [ ] GPU OOM watchdog
- [ ] Graceful shutdown: VST drain, Perception pipeline stop, NVR drain in-flight requests
- [ ] Runbooks: VST recovery, Perception pipeline restart, model rollback, Postgres restore, secrets rotation
- [ ] CI matrix builds (3 repos)
- [ ] Test coverage gate raised to 35%

**Phase 1 deliverable:** Vizor NVR running Metropolis VST + Perception FRS. Python FRS gone. Foundation proven. Architecture viable.

---

# Phase 2 — Metropolis Microservices Adoption (Weeks 13-26)

**Goal:** Replace remaining Python workers with Metropolis pipelines. Add new capabilities (LPR, MTMC, Behavior Analytics, Visual Search). Enterprise UX features.

**Exit criteria:**
- All Python AI workers decommissioned, `vizor-gpu` archived
- VST replaces go2rtc/ffmpeg for recording (go2rtc kept for WebRTC live)
- MTMC Microservice: cross-cam tracking live
- Behavior Analytics: zones, lines, dwell, occupancy
- LPR pipeline new
- Multi-cam sync playback + SSO + push notifs + rules engine UI
- License management

## Phase 2 Tasks

### 2.1 VST Becomes Primary Recording (Week 13-14)
- [ ] Migrate existing camera recordings from go2rtc/ffmpeg to VST (parallel run, validate)
- [ ] go2rtc retained for WebRTC live preview only
- [ ] Recording schedule UI feeds VST per-stream config
- [ ] Retention policy enforced by VST

### 2.2 PPE Pipeline on Perception (Week 14-16)
- [ ] TAO Toolkit: fine-tune PeopleNet head with PPE classes (helmet, vest, mask, gloves)
- [ ] Export ONNX → TensorRT plan via TAO
- [ ] DeepStream config: PGIE PeopleNet + SGIE custom PPE classifier
- [ ] Bridge: emit PPE compliance events to NVR ingest
- [ ] Frontend: PPE compliance dashboard
- [ ] Dual-run + cutover Python PPE worker

### 2.3 People Mgmt + Behavior Analytics (Week 15-17)
- [ ] Behavior Analytics Microservice deploy
- [ ] Per-camera zones, lines, dwell rules configured via NVR backend → Behavior Analytics API
- [ ] Migrate People Mgmt scenarios to Behavior Analytics + Perception
- [ ] Frontend: zone/line editor on camera view
- [ ] Dashboards: occupancy live + historical
- [ ] Dual-run + cutover Python People worker

### 2.4 MTMC Microservice — Cross-Cam Tracking (Week 17-19)
- [ ] MTMC deploy, configure ReIDNet via Triton
- [ ] Bridge: MTMC global track IDs → NVR `frs_investigations` system
- [ ] Frontend: person journey view across cameras
- [ ] Replace custom investigation logic with MTMC queries

### 2.5 LPR Pipeline (Week 19-21)
- [ ] DeepStream config: PGIE LPDNet + SGIE LPRNet (US/EU/IN region)
- [ ] NVR schema: `lpr_plates` (id, plate_text, region, confidence, event_id FK, vehicle_attrs JSONB) — hypertable
- [ ] `lpr_watchlists` (id, name, plates TEXT[], action_rule_id FK)
- [ ] LPR UI: plates search, watchlist mgmt, alerts on hit
- [ ] Integration: parking gates, vehicle entry/exit

### 2.6 Vizor Query → Visual Search Microservice OR Qdrant Adapter (Week 21-23)
- [ ] Option A: Deploy Visual Search Microservice (Milvus + CLIP). Migrate Qdrant vectors
- [ ] Option B: Keep Qdrant. Build adapter so frontend uses uniform API
- [ ] Recommend Option B for Phase 2 — less migration risk
- [ ] Cutover Python Vizor Query worker

### 2.7 Multi-Cam Sync Playback (Week 22-23)
- [ ] Backend: `/api/playback/multicam` returns VST segment lists per camera with shared time index
- [ ] Frontend: synchronized scrub bar drives N video elements
- [ ] Export multi-cam time range as ZIP with aligned MP4s

### 2.8 SSO + Enterprise Auth — DEFERRED to Phase 4
User decision: not needed in Phase 2. Defer SSO/LDAP/SAML until enterprise procurement actively asks. Re-evaluate in Phase 4 compliance work alongside SOC2.

### 2.9 Event Rules Engine + Alarm Workflow (Week 24-26)
- [ ] Schema: `rules` (conditions JSONB, actions JSONB, priority), `rule_executions` hypertable
- [ ] Rules DSL: AND/OR, camera_in, time_window, event_type, confidence_gte, person_in_group, attribute_match
- [ ] Actions: email, SMS, webhook, push notification, alarm, PTZ preset, record clip
- [ ] Visual rule builder UI
- [ ] Alarm states: new → ack → in_progress → resolved → closed
- [ ] SLA tracking, auto-escalation
- [ ] Alarm UI with sound, color severity, ack, assign

### 2.10 Mobile Push (Week 25-26)
- [ ] Firebase Cloud Messaging (Android) + APNs (iOS)
- [ ] Notification preference UI
- [ ] Snapshot attachment in push

### 2.11 License Management (Week 26)
- [ ] Per-camera license model
- [ ] Per-feature license (LPR add-on, FRS add-on, Federation)
- [ ] Grace period + expiry warnings
- [ ] Online activation or offline dongle

### 2.12 Decommission vizor-gpu (Week 26)
- [ ] Verify all Python workers replaced by Metropolis
- [ ] Archive `vizor-gpu/` to `git tag vizor-gpu-final`
- [ ] Remove `vizor-gpu/*` services from compose
- [ ] Update docs

**Phase 2 deliverable:** Full Metropolis adoption. All custom Python AI dead. Enterprise UX features. Vendor parity reached. Procurement-friendly.

---

# Phase 3 — Scale + Differentiation (Weeks 27-40)

**Goal:** Scale to 256 cameras/node. Add anomaly, action, advanced analytics. Federation across multiple NVR instances. HA + DR.

## Phase 3 Tasks

### 3.1 Vehicle Attributes Pipeline (Week 27-28)
- [ ] DeepStream: TrafficCamNet PGIE + VehicleType + VehicleMake + VehicleColor SGIE
- [ ] Bridge: extended vehicle attributes in event attributes JSONB
- [ ] Smart City vertical foundation

### 3.2 Action Recognition (Week 28-30)
- [ ] DeepStream: ActionRecognitionNet pipeline (running, fighting, falling, throwing, climbing)
- [ ] Rules engine integration: trigger on action_type
- [ ] Use case: public safety, manufacturing safety

### 3.3 Anomaly Detection (Week 30-32)
- [ ] TAO Toolkit: train autoencoder on per-camera baseline (first 7 days = normal)
- [ ] DeepStream custom SGIE invokes anomaly model via Triton
- [ ] Anomaly score per frame, threshold tunable
- [ ] UI: anomaly timeline, score graph, false-positive feedback loop
- [ ] Differentiator vs competitors

### 3.4 MMJ — LLM Video Q&A (Week 32-34)
- [ ] MMJ Microservice deploy (NVIDIA Metropolis component)
- [ ] Natural language: "show me red truck at gate Tuesday 3pm"
- [ ] Backend integration: replace Ollama Copilot OR augment
- [ ] Frontend: chat-style query interface

### 3.5 Re-Analyze Historical Footage (Week 33-35)
- [ ] Perception accepts VST recording URI: `nvurisrcbin` reads MP4 segments offline
- [ ] Inference job scheduler: select cameras + time range + model → batch infer
- [ ] UI: select range, start job, see progress
- [ ] Use case: deploy new model → run on last 30 days → find missed events

### 3.6 Spatial Intelligence + Map View (Week 34-36)
- [ ] Spatial Intelligence Microservice
- [ ] Floor plan upload, camera positions, FOV cones
- [ ] Heatmap overlay on map
- [ ] Multi-floor coordination

### 3.7 Federation Controller (Week 36-39)
- [ ] New service `vizor-federation` (lightweight FastAPI)
- [ ] Each NVR node registers, sends health + camera roster
- [ ] Unified SSO across cluster
- [ ] Global search (Visual Search across nodes)
- [ ] Cross-NVR event correlation
- [ ] Site management UI

### 3.8 HA Failover (Week 38-40)
- [ ] Postgres streaming replication
- [ ] Standby NVR shadow mode → promote on heartbeat miss
- [ ] VST recording continuity from secondary
- [ ] Failover/failback runbooks

### 3.9 256-Camera Scale (Week 36-40 parallel)
- [ ] Perception nvstreammux batching tuned (32 streams × 8 pipelines = 256)
- [ ] Postgres tuning: shared_buffers, work_mem
- [ ] Read replicas
- [ ] PgBouncer connection pool
- [ ] Redis Cluster
- [ ] Storage IO benchmarking
- [ ] Load test: 256 sim cameras + multiple analytics + 100 concurrent users

### 3.10 Storage Tiering (Week 40)
- [ ] Hot SSD (24-48h) → warm HDD (2-14d) → cold S3 (14+d)
- [ ] VST storage backend supports tiering, configure
- [ ] Background migrator
- [ ] Transparent retrieval

### 3.11 DR Replication (Week 40)
- [ ] Cross-site recording mirror
- [ ] RTO/RPO targets
- [ ] DR runbook + tested

**Phase 3 deliverable:** Best-in-class AI VMS. Multi-site enterprise. 256 cam/node. Anomaly + action + spatial.

---

# Phase 4 — Verticals + Mobile + Compliance (Weeks 41-52)

## Phase 4 Tasks

### 4.1 iOS App (Week 41-45)
- [ ] React Native or Swift native
- [ ] Live grid + playback + events + alarms + push
- [ ] Face ID / Touch ID
- [ ] PTZ touch
- [ ] App Store submission

### 4.2 Android App (Week 41-45 parallel)
- [ ] React Native shared codebase or native Kotlin
- [ ] Same feature set
- [ ] FCM push
- [ ] Play Store submission

### 4.3 Electron Desktop (Week 43-46)
- [ ] Bundle React frontend as Electron
- [ ] Multi-window: live view, alarm console, playback separate
- [ ] System tray + native notifs
- [ ] Auto-update channel
- [ ] Windows + Mac + Linux installers

### 4.4 Retail Vertical Pack (Week 45-47)
- [ ] Behavior Analytics: people counting at entry/exit, dwell, queue length
- [ ] Heatmap by hour
- [ ] Conversion correlation (footfall vs POS via webhook in)
- [ ] Pre-built dashboard

### 4.5 Banking Vertical Pack (Week 46-48)
- [ ] FRS watchlist for fraudsters
- [ ] ATM monitoring (tamper, loitering)
- [ ] Cash counter behavior
- [ ] Mask compliance
- [ ] Pre-built dashboard

### 4.6 Manufacturing Vertical Pack (Week 47-49)
- [ ] PPE compliance dashboard
- [ ] Zone safety (no-go, machinery proximity)
- [ ] Worker count per shift
- [ ] Incident replay
- [ ] OSHA-style compliance report

### 4.7 Smart City Vertical Pack (Week 48-50)
- [ ] LPR + vehicle attrs
- [ ] Crowd density
- [ ] Traffic flow + congestion
- [ ] Public safety incidents (fight, fall, intrusion)
- [ ] Integration: city alarm centers

### 4.8 Logistics Vertical Pack (Week 49-51)
- [ ] Vehicle/container tracking
- [ ] Loading bay (dock occupancy, dwell)
- [ ] Worker safety in yard
- [ ] LPR gate access

### 4.9 SOC2 Type 1 Prep (Week 49-52)
- [ ] Security policies docs
- [ ] Access control review
- [ ] Encryption at rest + transit audit
- [ ] Audit log retention 1 yr
- [ ] Pen test + remediation
- [ ] Vendor mgmt
- [ ] Engage auditor

### 4.10 GDPR + India DPDP (Week 50-52)
- [ ] Data subject rights API
- [ ] Privacy notice + consent
- [ ] DPO contact + breach notification
- [ ] Encryption verify
- [ ] DPIA template

### 4.11 Benchmark Suite (Week 52)
- [ ] Open-source benchmark scripts
- [ ] Compare vs Frigate, vs Hik, vs Milestone
- [ ] Metrics: cams/node, AI throughput, latency, storage efficiency
- [ ] Marketing whitepaper

### 4.12 API Docs + SDK (Week 50-52)
- [ ] OpenAPI spec
- [ ] Docs site (Mintlify / Docusaurus)
- [ ] Python SDK + JavaScript SDK
- [ ] Postman collection

**Phase 4 deliverable:** 5 vertical packs. Mobile + desktop. SOC2 Type 1 in flight. India + global enterprise sales motion.

---

# Risk Register

| Risk | Mitigation |
|---|---|
| Metropolis Microservices not all GA | Use only GA: VST, Perception, MTMC, Behavior Analytics, Event, Visual Search. Skip preview |
| NVIDIA can change APIs | Pin LTS version per release. Thin adapter layer to swap if needed |
| Pretrained model quality on Indian data | TAO fine-tune with customer samples. Standard ML workflow |
| Mongo data loss during cutover | Backup + dual-write + 90 day archive |
| Customer wants air-gapped | Metropolis works air-gapped. NGC models offline-downloadable |
| Team DeepStream ramp time | Budget 2-3 wks for 1-2 engineers. Use NVIDIA samples |
| ~30-50 GB Docker stack | Pre-pull on deploy nodes. Layer caching |
| GPU resource contention | Reserve GPU memory per microservice. Monitor via Prometheus |
| Customer-facing webhook break | Forward old webhooks from vizor-app to NVR during cutover |

---

# Headcount Optimal

- **2 backend engineers** (Python, Postgres, FastAPI, adapter layers)
- **1 frontend engineer** (React, video, complex UI)
- **1 ML/AI engineer** (DeepStream pipelines, TAO training, NGC models)
- **1 DevOps/SRE** (CI, deploy, observability, Metropolis stack ops)
- **1 QA** (test automation, regression)
- **1 designer** (part-time, UX)
- **1 PM** (part-time)

= **~5 FTE engineering + 1 QA**. Solo or pair will take 2-3x longer.

---

# Phase Gates

| Gate | P1→P2 | P2→P3 | P3→P4 |
|---|---|---|---|
| All exit criteria met | Yes | Yes | Yes |
| Test coverage floor | 35% | 50% | 65% |
| CI green 7 days | Yes | Yes | Yes |
| Production validated | Yes | Yes | Yes |
| Runbooks updated | Yes | Yes | Yes |
| Critical issues open | <10 | <5 | 0 |
| Perf regression check | Yes | Yes | Yes |
| Security review | Light | Full | Full + pen test |

---

# Document Status

- **Version:** 2.0 (Metropolis-native pivot)
- **Created:** 2026-05-13
- **Owner:** Vizor team
- **Review cadence:** Monthly
- **Living document:** Yes — update as phases progress
