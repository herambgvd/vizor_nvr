# =============================================================================
# Application Configuration
# =============================================================================
# Single source of truth for all configuration values.
# Reads from environment variables with sensible defaults.
# =============================================================================

import os
import secrets
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Resolve paths relative to backend/ directory
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / ".env")


class Settings:
    """Application settings loaded from environment variables."""

    # ── Database ────────────────────────────────────────────────────────
    # PostgreSQL (production): postgresql+asyncpg://nvr:pass@localhost:5432/gvd_nvr
    # SQLite    (dev/fallback): leave empty
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Only used when DATABASE_URL is empty (SQLite fallback)
    DATABASE_PATH: str = os.getenv(
        "DATABASE_PATH", str(ROOT_DIR / "data" / "nvr_database.db")
    )

    # ── JWT / Security ──────────────────────────────────────────────────
    _env_secret = os.getenv("JWT_SECRET_KEY", "")
    if _env_secret:
        JWT_SECRET_KEY: str = _env_secret
    else:
        JWT_SECRET_KEY: str = secrets.token_urlsafe(64)
        logger.warning(
            "JWT_SECRET_KEY not set — generated random key. "
            "Tokens will be invalidated on restart."
        )

    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_HOURS: int = int(
        os.getenv("JWT_ACCESS_TOKEN_EXPIRE_HOURS", "24")
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(
        os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30")
    )

    # ── CORS ────────────────────────────────────────────────────────────
    _cors_env = os.getenv("CORS_ORIGINS", "")
    if _cors_env and _cors_env != "*":
        CORS_ORIGINS: list = [o.strip() for o in _cors_env.split(",") if o.strip()]
    else:
        CORS_ORIGINS: list = [
            "http://localhost:3000",
            "http://localhost:3006",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3006",
        ]

    # ── Storage Paths ───────────────────────────────────────────────────
    STORAGE_PATH: str = os.getenv(
        "STORAGE_PATH", str(ROOT_DIR / "data" / "recordings")
    )
    THUMBNAIL_PATH: str = os.getenv(
        "THUMBNAIL_PATH", str(ROOT_DIR / "data" / "thumbnails")
    )
    HLS_PATH: str = os.getenv("HLS_PATH", str(ROOT_DIR / "data" / "hls"))
    EXPORT_PATH: str = os.getenv(
        "EXPORT_PATH", str(ROOT_DIR / "data" / "exports")
    )
    DATA_PATH: str = os.getenv("DATA_PATH", str(ROOT_DIR / "data"))
    CERT_PATH: str = os.getenv("CERT_PATH", str(ROOT_DIR / "data" / "certs"))
    # If set, certs uploaded via /api/settings/tls/upload are also written to
    # this path (typically the path nginx mounts). When unset, only the
    # canonical CERT_PATH is used.
    NGINX_CERT_PATH: str = os.getenv("NGINX_CERT_PATH", "")

    # ── go2rtc ──────────────────────────────────────────────────────────
    GO2RTC_URL: str = os.getenv("GO2RTC_URL", "http://localhost:1984")
    GO2RTC_RTSP_PORT: int = int(os.getenv("GO2RTC_RTSP_PORT", "8554"))

    # ── Cloud Storage (S3-compatible: AWS S3, MinIO, Backblaze B2) ────
    CLOUD_STORAGE_ENABLED: bool = (
        os.getenv("CLOUD_STORAGE_ENABLED", "false").lower() == "true"
    )
    CLOUD_S3_ENDPOINT: str = os.getenv("CLOUD_S3_ENDPOINT", "")
    CLOUD_S3_BUCKET: str = os.getenv("CLOUD_S3_BUCKET", "")
    CLOUD_S3_REGION: str = os.getenv("CLOUD_S3_REGION", "us-east-1")
    CLOUD_S3_ACCESS_KEY: str = os.getenv("CLOUD_S3_ACCESS_KEY", "")
    CLOUD_S3_SECRET_KEY: str = os.getenv("CLOUD_S3_SECRET_KEY", "")
    CLOUD_S3_PREFIX: str = os.getenv("CLOUD_S3_PREFIX", "recordings/")

    # ── Recording Defaults ──────────────────────────────────────────────
    DEFAULT_SEGMENT_DURATION: int = int(
        os.getenv("SEGMENT_DURATION_SECONDS", "900")
    )  # 15 min

    # ── FFmpeg Recovery ─────────────────────────────────────────────────
    FFMPEG_RECOVERY_ENABLED: bool = (
        os.getenv("FFMPEG_RECOVERY_ENABLED", "true").lower() == "true"
    )
    FFMPEG_HEALTH_CHECK_INTERVAL: int = int(
        os.getenv("FFMPEG_HEALTH_CHECK_INTERVAL", "30")
    )
    FFMPEG_GLOBAL_PROCESS_CAP: int = int(
        os.getenv("FFMPEG_GLOBAL_PROCESS_CAP", "192")
    )  # Max concurrent FFmpeg processes across recording, motion, prebuffer
    # Hardware encoder selection for FFmpeg re-encode paths (privacy masks).
    # auto = detect best | nvenc | vaapi | videotoolbox | software
    HARDWARE_TRANSCODING: str = os.getenv("HARDWARE_TRANSCODING", "auto")

    # ── Redis (event bus + cache) ──────────────────────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    # ── Server ──────────────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    ENV: str = os.getenv("ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── Cluster ─────────────────────────────────────────────────────────
    # NVR_NODE_ID: unique identifier for this node; defaults to hostname
    NVR_NODE_ID: str = os.getenv("NVR_NODE_ID", "")
    NVR_NODE_IP: str = os.getenv("NVR_NODE_IP", "")
    CLUSTER_HEARTBEAT_INTERVAL: int = int(
        os.getenv("CLUSTER_HEARTBEAT_INTERVAL", "5")
    )
    CLUSTER_LEASE_TTL: int = int(os.getenv("CLUSTER_LEASE_TTL", "15"))
    # Minimum seconds between repeated cluster role-change events; guards
    # against restart loops spamming the alarms panel.
    CLUSTER_EVENT_COOLDOWN_SECS: int = int(
        os.getenv("CLUSTER_EVENT_COOLDOWN_SECS", "60")
    )

    # ── POS / ATM Overlay ───────────────────────────────────────────────
    # POS_OVERLAY_PORT: TCP port for receipt-printer serial-over-IP devices
    # (default 9100 = raw-print protocol; change to avoid conflict if needed)
    POS_OVERLAY_PORT: int = int(os.getenv("POS_OVERLAY_PORT", "9100"))
    POS_OVERLAY_HOST: str = os.getenv("POS_OVERLAY_HOST", "0.0.0.0")
    # POS_MAX_MESSAGE_BYTES: close connection if a single message exceeds this
    POS_MAX_MESSAGE_BYTES: int = int(os.getenv("POS_MAX_MESSAGE_BYTES", "4096"))
    # POS_BUFFER_LAST_N: messages buffered per-IP when no camera is assigned yet
    POS_BUFFER_LAST_N: int = int(os.getenv("POS_BUFFER_LAST_N", "20"))

    # ── ANR (Automatic Network Replenishment) ───────────────────────────
    # ANR_DEBOUNCE_SECONDS: camera must be stable online for this long before
    # ANR is triggered (avoids false-fires on transient blips)
    ANR_DEBOUNCE_SECONDS: int = int(os.getenv("ANR_DEBOUNCE_SECONDS", "60"))
    # ANR_SEGMENT_DURATION: seconds per download chunk
    ANR_SEGMENT_DURATION: int = int(os.getenv("ANR_SEGMENT_DURATION", "600"))

    # ── Dewarp ──────────────────────────────────────────────────────────
    # DEWARP_MAX_CONCURRENT: max simultaneous dewarp FFmpeg jobs (CPU guard)
    DEWARP_MAX_CONCURRENT: int = int(os.getenv("DEWARP_MAX_CONCURRENT", "4"))
    # DEWARP_FALLBACK_WIDTH/HEIGHT: used when no GPU encoder available
    DEWARP_FALLBACK_WIDTH: int = int(os.getenv("DEWARP_FALLBACK_WIDTH", "1280"))
    DEWARP_FALLBACK_HEIGHT: int = int(os.getenv("DEWARP_FALLBACK_HEIGHT", "720"))

    # ── RAID ────────────────────────────────────────────────────────────
    # RAID_POLL_INTERVAL: seconds between degraded-state checks
    RAID_POLL_INTERVAL: int = int(os.getenv("RAID_POLL_INTERVAL", "60"))

    # ── Archive / Scheduled Backup ──────────────────────────────────────
    # ARCHIVE_CHECK_INTERVAL: seconds between cron schedule evaluations
    ARCHIVE_CHECK_INTERVAL: int = int(os.getenv("ARCHIVE_CHECK_INTERVAL", "60"))
    # ARCHIVE_NAS_MAX_BACKOFF: maximum retry backoff in seconds when NAS down
    ARCHIVE_NAS_MAX_BACKOFF: int = int(
        os.getenv("ARCHIVE_NAS_MAX_BACKOFF", "960")
    )  # 16 minutes

    # ── Twilio (SMS + WhatsApp) ─────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")
    TWILIO_WHATSAPP_FROM: str = os.getenv("TWILIO_WHATSAPP_FROM", "")
    # SMS_RATE_LIMIT_PER_HOUR: max SMS per recipient per hour (billing guard)
    SMS_RATE_LIMIT_PER_HOUR: int = int(os.getenv("SMS_RATE_LIMIT_PER_HOUR", "5"))
    # WA_RATE_LIMIT_PER_HOUR: same guard for WhatsApp
    WA_RATE_LIMIT_PER_HOUR: int = int(os.getenv("WA_RATE_LIMIT_PER_HOUR", "5"))

    # ── Helpers ─────────────────────────────────────────────────────────

    def ensure_directories(self):
        """Create all storage directories if they don't exist."""
        for p in (
            self.STORAGE_PATH,
            self.THUMBNAIL_PATH,
            self.HLS_PATH,
            self.EXPORT_PATH,
            self.DATA_PATH,
            self.CERT_PATH,
        ):
            Path(p).mkdir(parents=True, exist_ok=True)

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


# Module-level singleton
settings = Settings()
