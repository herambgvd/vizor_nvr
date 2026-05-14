# Metropolis Deployment Configs

This directory holds NVIDIA DeepStream + Metropolis Microservice
configuration that the Vizor NVR backend pushes to a running Perception
service. Files are **declarative**; the Perception Microservice runtime
loads + applies them.

Layout:

```
metropolis/
├── perception/                # DeepStream pipeline configs
│   ├── common/                # Shared elements (tracker, msgbroker)
│   ├── frs/                   # Face Recognition pipeline
│   └── people_counting/       # People counting + occupancy
├── vst/                       # VST (Video Storage Toolkit) configs
└── behavior_analytics/        # Zones, lines, dwell rules
```

## How Vizor uses these

1. Operator enables a scenario on a camera via the UI (`PUT
   /api/ai/cameras/{id}/scenarios/{slug}`)
2. NVR backend writes a `camera_ai_configs` row with the resolved config
3. A scenario-to-DS-config translator (Phase 1.9.c, deferred to GPU
   arrival) renders a per-camera DS pipeline config from the template
   files here
4. Backend pushes the rendered config to Perception Microservice REST
5. Perception spawns/updates the DeepStream pipeline
6. Detection events flow back via `nvmsgbroker` → Redis Stream → bridge

## Why config-as-code

- Reproducible deploys
- Diff-able in git when models or thresholds change
- Same files run on dev RTX 4050 (1-2 cams) and prod RTX 5060 (30-50 cams)
- Survive Perception Microservice version upgrades — only the pipeline
  spec is ours, the runtime is NVIDIA's

## Status

| Pipeline | Status | Models |
|---|---|---|
| FRS | Config ready, runtime test pending RTX 5060 | FaceDetectIR + ArcFace |
| People Counting | Config ready, runtime test pending RTX 5060 | PeopleNet + nvdsanalytics |
| PPE | Phase 2 | PeopleNet + custom TAO PPE classifier |
| LPR | Phase 2 | LPDNet + LPRNet |
| Vehicle Analytics | Phase 3 | TrafficCamNet + attribute SGIEs |
| Action Recognition | Phase 3 | ActionRecognitionNet |
| Cross-Cam ReID (MTMC) | Phase 3 | ReIDNet |
| Anomaly | Phase 3 | Custom autoencoder via TAO |

## Hardware notes

- **RTX 4050 6GB (dev)**: max 2-4 cams composite — FRS + PeopleNet co-tenant
- **RTX 5060 16GB (prod target)**: 30-50 cams composite, all GA scenarios
- **T4 16GB**: 30-50 cams, similar profile to 5060 but lower clock
- **L4 24GB**: 50-100 cams, sweet spot for site deployments
- **A100 40GB+**: 200+ cams for federation hub
