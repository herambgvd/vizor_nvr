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
    # Hardware encoder selection for FFmpeg re-encode paths (privacy masks).
    # auto = detect best | nvenc | vaapi | videotoolbox | software
    HARDWARE_TRANSCODING: str = os.getenv("HARDWARE_TRANSCODING", "auto")

    # ── Redis (event bus + cache) ──────────────────────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    # ── AI / Inference ─────────────────────────────────────────────────
    QDRANT_URL: str = os.getenv("QDRANT_URL", "")
    TRITON_URL: str = os.getenv("TRITON_URL", "")
    # Bridge between DeepStream / Metropolis event streams and the
    # /api/events/ingest endpoint. Single-process consumer per backend
    # replica.
    METROPOLIS_BRIDGE_ENABLED: bool = (
        os.getenv("METROPOLIS_BRIDGE_ENABLED", "false").lower() == "true"
    )
    # Redis stream key the bridge listens on (DeepStream publishes here)
    AI_EVENT_STREAM: str = os.getenv("AI_EVENT_STREAM", "ai:events")
    AI_EVENT_GROUP: str = os.getenv("AI_EVENT_GROUP", "nvr-bridge")

    # ── Server ──────────────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    ENV: str = os.getenv("ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

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
