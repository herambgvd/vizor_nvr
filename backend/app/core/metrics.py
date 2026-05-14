# =============================================================================
# Prometheus metrics — NVR-specific instruments.
#
# The HTTP request / latency series come from prometheus-fastapi-instrumentator
# (wired in app/main.py). This module defines domain metrics that producing
# services update directly.
#
# Usage::
#
#     from app.core.metrics import EVENTS_INGESTED
#     EVENTS_INGESTED.labels(source_service="vizor-gpu-frs").inc()
# =============================================================================

from prometheus_client import Counter, Gauge, Histogram


# ── Event ingest ─────────────────────────────────────────────────────────
EVENTS_INGESTED = Counter(
    "vizor_events_ingested_total",
    "Number of AI detection events successfully inserted via /api/events/ingest",
    labelnames=("source_service", "detection_type"),
)

EVENTS_SKIPPED = Counter(
    "vizor_events_skipped_total",
    "Number of AI detection events skipped due to dedup_key conflict",
    labelnames=("source_service",),
)

EVENTS_FAILED = Counter(
    "vizor_events_failed_total",
    "Number of AI detection events that failed to insert",
    labelnames=("source_service",),
)

INGEST_BATCH_SIZE = Histogram(
    "vizor_events_ingest_batch_size",
    "Distribution of batch sizes received at /api/events/ingest",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500),
)


# ── API key auth ──────────────────────────────────────────────────────────
API_KEY_AUTH = Counter(
    "vizor_api_key_auth_total",
    "API key authentication attempts",
    labelnames=("result",),   # "ok" | "invalid" | "revoked" | "expired"
)


# ── Recording / FFmpeg ────────────────────────────────────────────────────
ACTIVE_CAMERAS = Gauge(
    "vizor_active_cameras",
    "Cameras currently enabled in the NVR",
)

ACTIVE_RECORDINGS = Gauge(
    "vizor_active_recordings",
    "FFmpeg recording processes currently running",
)

RECORDING_BYTES_TOTAL = Counter(
    "vizor_recording_bytes_total",
    "Total bytes written to recording storage",
    labelnames=("camera_id",),
)

FFMPEG_RESTARTS = Counter(
    "vizor_ffmpeg_restarts_total",
    "Number of times the FFmpeg supervisor has restarted a recording process",
    labelnames=("camera_id", "reason"),
)


# ── Storage ───────────────────────────────────────────────────────────────
STORAGE_USED_BYTES = Gauge(
    "vizor_storage_used_bytes",
    "Bytes used per storage pool",
    labelnames=("pool",),
)

STORAGE_FREE_BYTES = Gauge(
    "vizor_storage_free_bytes",
    "Bytes free per storage pool",
    labelnames=("pool",),
)


# ── go2rtc ────────────────────────────────────────────────────────────────
GO2RTC_HEALTHY = Gauge(
    "vizor_go2rtc_healthy",
    "1 if the go2rtc relay reported healthy on the last check, else 0",
)


# ── Camera health ─────────────────────────────────────────────────────────
CAMERA_ONLINE = Gauge(
    "vizor_camera_online",
    "1 if the camera reported online in the latest health snapshot, else 0",
    labelnames=("camera_id",),
)


# ── ONVIF event puller ────────────────────────────────────────────────────
ONVIF_EVENTS_RECEIVED = Counter(
    "vizor_onvif_events_total",
    "ONVIF events received from cameras",
    labelnames=("camera_id", "topic"),
)
