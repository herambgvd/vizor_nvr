# Scenario template

Copy this folder to start a new AI scenario plugin. It is a minimal, working
**detect → alert** scenario built entirely on the Vizor Scenario SDK
(`scenarios/_sdk`). You write only the scenario-specific parts; the SDK provides
Triton inference, frame pulling, NVR registration/auth, tracking, rules, and the
event schema.

## What you edit

```
<your-scenario>/
├── scenario.json     manifest — slug, name, license_feature, tabs, event_types,
│                     camera_config_schema. Edit ALL fields.
├── config/settings.py  Config(BaseConfig) — add your thresholds + model names.
├── detect.py         the ONE scenario-specific piece: call your Triton model(s),
│                     return detections. Pre/post-processing lives here.
├── logic.py          turn detections into events (rule: match? threshold?
│                     line-cross? dwell?). Uses SDK rules/tracker as needed.
├── app.py            wire it together with build_app() — usually unchanged.
├── requirements.txt  fastapi/uvicorn + the SDK (installed in the image).
└── Dockerfile        copies the SDK in and installs it (see below).
```

## The 5-minute checklist

1. `cp -r scenarios/_template scenarios/<slug>`
2. Edit `scenario.json` — slug, name, `license_feature`, `event_types`, config schema.
3. `config/settings.py` — set `SLUG`, model names, thresholds.
4. `detect.py` — implement `detect(frame_bgr) -> list[Detection]` against your
   Triton model. Drop the model into `triton/model_repository/<model>/`.
5. `logic.py` — implement `evaluate(detections, camera_id) -> list[event dict]`.
6. Add a service block to `docker-compose.ai.yml` (copy an existing one, change
   slug/port).
7. `docker compose ... up -d <slug>` — `/health` should report ok + model ready.

## Families

- **detect → alert** (Gun, Fire/Smoke, Pose): this template as-is — detect, threshold, emit.
- **detect → track → rule** (Loitering, In/Out, Crowd, PPE): add `ByteTracker` +
  `rules.py` (`Zone` / `LineCrossCounter` / `DwellTracker`) in `logic.py`.
- **detect → embed → match** (FRS, ANPR, Suspect Search): add `QdrantStore` and an
  embed step in `detect.py`; match in `logic.py`.

See `scenarios/anpr` for a vector-match example and the existing FRS/SS plugins
for full production scenarios.
