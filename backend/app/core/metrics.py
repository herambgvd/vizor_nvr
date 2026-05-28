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
    "Number of NVR events successfully inserted via /api/events/ingest",
    labelnames=("source_service",),
)

EVENTS_SKIPPED = Counter(
    "vizor_events_skipped_total",
    "Number of NVR events skipped due to dedup_key conflict",
    labelnames=("source_service",),
)

EVENTS_FAILED = Counter(
    "vizor_events_failed_total",
    "Number of NVR events that failed to insert",
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


# ── Cluster ───────────────────────────────────────────────────────────────
GVD_CLUSTER_ROLE = Gauge(
    "gvd_cluster_role",
    "Current cluster role: 1 = leader/active, 0 = standby",
    labelnames=("node",),
)

GVD_CLUSTER_HEARTBEAT_LATE = Counter(
    "gvd_cluster_heartbeat_late_total",
    "Number of times cluster heartbeat was delayed beyond lease TTL",
    labelnames=("node",),
)


# ── FFmpeg Governor ───────────────────────────────────────────────────────
GVD_FFMPEG_ACTIVE_PROCESSES = Gauge(
    "gvd_ffmpeg_active_processes",
    "Number of FFmpeg process slots currently in use",
)

GVD_FFMPEG_GOVERNOR_CAP = Gauge(
    "gvd_ffmpeg_governor_cap",
    "Configured maximum concurrent FFmpeg processes (governor cap)",
)

GVD_FFMPEG_GOVERNOR_REJECTED = Counter(
    "gvd_ffmpeg_governor_rejected_total",
    "Requests rejected by FFmpeg governor because cap was reached",
)


# ── RAID ──────────────────────────────────────────────────────────────────
GVD_RAID_ARRAY_DEGRADED = Gauge(
    "gvd_raid_array_degraded",
    "1 if the RAID array has at least one failed device, else 0",
    labelnames=("device",),
)

GVD_RAID_FAILED_DEVICES = Gauge(
    "gvd_raid_failed_devices",
    "Number of failed devices in a RAID array",
    labelnames=("device",),
)


# ── Archive ───────────────────────────────────────────────────────────────
GVD_ARCHIVE_JOB_DURATION = Histogram(
    "gvd_archive_job_duration_seconds",
    "Time taken by an archive/backup job to complete",
    buckets=(30, 60, 120, 300, 600, 1800, 3600, 7200),
)

GVD_ARCHIVE_JOB_FAILURES = Counter(
    "gvd_archive_job_failures_total",
    "Number of archive jobs that completed with failures",
)

GVD_ARCHIVE_NAS_BACKOFF = Gauge(
    "gvd_archive_nas_backoff_seconds",
    "Current backoff delay (seconds) when NAS is unreachable; 0 = healthy",
)


# ── SMS / WhatsApp ────────────────────────────────────────────────────────
GVD_SMS_SENT = Counter(
    "gvd_sms_sent_total",
    "SMS messages successfully dispatched",
)

GVD_SMS_FAILED = Counter(
    "gvd_sms_failed_total",
    "SMS messages that failed to send",
    labelnames=("reason",),
)

GVD_SMS_RATE_LIMITED = Counter(
    "gvd_sms_rate_limited_total",
    "SMS sends dropped because recipient hit the per-hour rate limit",
)

GVD_WHATSAPP_SENT = Counter(
    "gvd_whatsapp_sent_total",
    "WhatsApp messages successfully dispatched",
)

GVD_WHATSAPP_FAILED = Counter(
    "gvd_whatsapp_failed_total",
    "WhatsApp messages that failed to send",
    labelnames=("reason",),
)

GVD_WHATSAPP_RATE_LIMITED = Counter(
    "gvd_whatsapp_rate_limited_total",
    "WhatsApp sends dropped because recipient hit the per-hour rate limit",
)
