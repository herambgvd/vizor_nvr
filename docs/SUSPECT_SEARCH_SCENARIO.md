# Suspect Search Scenario

Suspect Search is a plugin scenario, not an NVR-core feature. The NVR owns cameras,
recordings, auth, licensing and playback links. The plugin owns archive indexing,
object crops, embeddings, Qdrant vectors, job state and search results.

## Camera Rule

- Scenario ON for a camera: new archive indexing/search metadata can be created.
- Scenario OFF for a camera: new indexing stops for that camera.
- Existing indexed metadata remains searchable after the camera is disabled.

This keeps historical investigations usable while preventing new processing on
disabled cameras.

## Search Pipeline

```text
recording catalog from NVR
  -> ffmpeg frame sampling
  -> YOLO ONNX detector: person, bag, helmet
  -> object crop
  -> color / size / position metadata
  -> ReID / embedding ONNX model
  -> Qdrant vector index
  -> chronological results with thumbnails and playback links
```

Search modes:

- Image/sample search: upload a person/object image and search similar crops.
- Attribute search: object type plus color, size and position filters.
- Nested search: select a result crop and search for visually similar results.

## Runtime Storage

The plugin persists runtime data in its own Postgres service:

- `suspect-search-db`: jobs and result metadata.
- `/data/suspect-search/thumbs`: result crops and thumbnails.

Qdrant stores vectors in the `vizor_suspect_search` collection.

The plugin can migrate an older local SQLite store from
`/data/suspect-search/suspect_search.sqlite3` once, then continues using
Postgres as the source of truth.

## Model Serving

Current production path is embedded ONNX Runtime inside the Suspect Search
container. Docker Compose mounts local model files into `/models`.

Required files:

```text
models/yolo26.onnx
models/person-reid.onnx
```

The compose service grants GPU access with `gpus: all`. Health should show
`CUDAExecutionProvider` and `model_ready: true` once both ONNX files are present.

Recommended model roles:

- `yolo26.onnx`: detector for `person`, `bag`, `helmet`.
- `person-reid.onnx`: embedding model for person similarity search.
- Later, add object-specific embedding models for bag/helmet if accuracy requires it.

## Health Checks

Use the NVR scenario gateway:

```bash
curl -sk -X POST https://localhost/api/ai/scenarios/suspect-search/proxy/health/deep \
  -H "Authorization: Bearer $TOKEN"
```

Expected with models mounted:

- `qdrant: true`
- `store.backend: postgres`
- `store.db_ready: true`
- `onnx.cuda_provider: true`
- `onnx.ready: true`

Without model files, the plugin is intentionally `degraded` and can only use the
fallback color/vector path.
