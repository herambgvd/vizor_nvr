"""Suspect Search public dashboard + third-party ingest — on the shared Vizor SDK.

Suspect Search is a FORENSIC archive-search tool (it runs index/search JOBS over
recorded video and stores match RESULTS), not a live event producer. It also does
NOT use SQLAlchemy — its store is raw psycopg2 (`jobs` + `results` tables). The
SDK's `SettingsStore` assumes a SQLAlchemy session/model, so here we provide a
duck-typed, psycopg2-backed store exposing the SAME public surface the SDK routers
use: `.get()`, `.update()`, `.rotate_key()`, `.verify_key()`. The SDK
build_public_router / build_ingest_router only call `.get()` and `.verify_key()`,
so they work against this shim unchanged — no new SQLAlchemy dependency.

Honesty notes:
  * dashboard() is a SENSIBLE-but-minimal aggregate over jobs/results (searches /
    candidates / matches today + hourly trend + by-camera from results). SS has
    little "live" data, so totals dominate.
  * ingest() records an external sighting/match into the `results` table when a
    result-shaped payload is posted; it is a best-effort convenience, not a core
    SS feature.
"""
from __future__ import annotations

import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from vizor_sdk import EventBus

from config.settings import DATABASE_URL

# Shared SDK in-process pub/sub for the public SSE stream. SS rarely produces live
# events, but an ingested sighting publishes here so the stream is functional.
bus = EventBus()

_SINGLETON_ID = "singleton"
_KEY_PREFIX = "ss"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_utc(dt: datetime) -> str:
    s = dt.isoformat()
    return s if (dt.tzinfo is not None) else s + "Z"


def _conn():
    # Local import so a missing driver doesn't break module import in dev.
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_settings_table() -> None:
    """Create the singleton settings table if absent (SS has no Alembic runner —
    this is the migration). Idempotent."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS suspect_search_settings (
                    id TEXT PRIMARY KEY,
                    public_dashboard_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    ingest_api_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    ingest_api_key VARCHAR(128),
                    public_show_names BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMPTZ
                )
                """
            )
        conn.commit()


class _PgSettingsStore:
    """psycopg2-backed, SDK-SettingsStore-compatible singleton store.

    Exposes the same methods the SDK SettingsStore does (get / update /
    rotate_key / verify_key) so it drops into build_public_router /
    build_ingest_router unchanged."""

    _FIELDS = ("public_dashboard_enabled", "ingest_api_enabled",
               "ingest_api_key", "public_show_names")

    def _ensure_row(self, cur) -> None:
        cur.execute(
            "INSERT INTO suspect_search_settings (id, updated_at) "
            "VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (_SINGLETON_ID, _utcnow()),
        )

    def get(self) -> dict:
        with _conn() as conn:
            with conn.cursor() as cur:
                self._ensure_row(cur)
                cur.execute(
                    "SELECT public_dashboard_enabled, ingest_api_enabled, "
                    "ingest_api_key, public_show_names "
                    "FROM suspect_search_settings WHERE id = %s",
                    (_SINGLETON_ID,),
                )
                r = cur.fetchone() or {}
            conn.commit()
        return {
            "public_dashboard_enabled": bool(r.get("public_dashboard_enabled")),
            "ingest_api_enabled": bool(r.get("ingest_api_enabled")),
            "ingest_api_key": r.get("ingest_api_key"),
            "public_show_names": bool(r.get("public_show_names")),
        }

    def update(self, **patch) -> dict:
        fields = {k: v for k, v in patch.items() if k in self._FIELDS}
        with _conn() as conn:
            with conn.cursor() as cur:
                self._ensure_row(cur)
                # Mint a key the first time ingest is enabled.
                if patch.get("ingest_api_enabled"):
                    cur.execute(
                        "SELECT ingest_api_key FROM suspect_search_settings WHERE id = %s",
                        (_SINGLETON_ID,),
                    )
                    cur_key = (cur.fetchone() or {}).get("ingest_api_key")
                    if not cur_key and "ingest_api_key" not in fields:
                        fields["ingest_api_key"] = self._mint()
                if fields:
                    sets = ", ".join(f"{k} = %s" for k in fields)
                    params = list(fields.values()) + [_utcnow(), _SINGLETON_ID]
                    cur.execute(
                        f"UPDATE suspect_search_settings SET {sets}, updated_at = %s "
                        f"WHERE id = %s",
                        params,
                    )
            conn.commit()
        return self.get()

    def rotate_key(self) -> str:
        new_key = self._mint()
        with _conn() as conn:
            with conn.cursor() as cur:
                self._ensure_row(cur)
                cur.execute(
                    "UPDATE suspect_search_settings SET ingest_api_key = %s, "
                    "updated_at = %s WHERE id = %s",
                    (new_key, _utcnow(), _SINGLETON_ID),
                )
            conn.commit()
        return new_key

    def verify_key(self, presented) -> bool:
        st = self.get()
        if not st["ingest_api_enabled"] or not st["ingest_api_key"]:
            return False
        return bool(presented) and hmac.compare_digest(
            str(presented), str(st["ingest_api_key"]))

    def _mint(self) -> str:
        return f"{_KEY_PREFIX}k_" + secrets.token_urlsafe(32)


store = _PgSettingsStore()


# ── dashboard ────────────────────────────────────────────────────────────────
def build_dashboard(settings: dict) -> dict:
    """Sensible-but-minimal aggregate over the SS jobs/results tables.

    SS is forensic (not live), so this leans on totals: searches today, indexed
    candidates, matches (results) today, an hourly trend of jobs/results, and a
    by-camera rollup from results. Identity-bearing detail is gated by show_names
    (SS results are mostly anonymous re-id crops, so little to gate)."""
    show_names = bool(settings.get("public_show_names"))
    now = _utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_24h = now - timedelta(hours=24)

    searches_today = 0
    indexed_candidates = 0
    matches_today = 0
    by_camera: list[dict] = []
    hourly_jobs: dict[str, int] = {}
    hourly_results: dict[str, int] = {}

    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                # Jobs created today (a "search"/"index" run).
                cur.execute(
                    "SELECT COUNT(*) AS n FROM jobs WHERE created_at >= %s "
                    "AND job_type = 'search'",
                    (day_start,),
                )
                searches_today = int((cur.fetchone() or {}).get("n") or 0)

                # Indexed candidates = sum over today's jobs' payload count.
                cur.execute(
                    "SELECT payload_json FROM jobs WHERE created_at >= %s",
                    (day_start,),
                )
                for row in cur.fetchall():
                    payload = row.get("payload_json") or {}
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except Exception:  # noqa: BLE001
                            payload = {}
                    indexed_candidates += int(payload.get("indexed_candidates") or 0)

                # Matches today = results rows timestamped today.
                cur.execute(
                    "SELECT COUNT(*) AS n FROM results WHERE timestamp >= %s",
                    (day_start,),
                )
                matches_today = int((cur.fetchone() or {}).get("n") or 0)

                # By-camera rollup from today's results.
                cur.execute(
                    "SELECT camera_id, COUNT(*) AS n FROM results "
                    "WHERE timestamp >= %s GROUP BY camera_id",
                    (day_start,),
                )
                by_camera = [{"camera_id": (r.get("camera_id") or "unknown"),
                              "count": int(r.get("n") or 0)}
                             for r in cur.fetchall()]

                # Hourly trend (24h) for jobs + results.
                cur.execute(
                    "SELECT created_at FROM jobs WHERE created_at >= %s",
                    (since_24h,),
                )
                for r in cur.fetchall():
                    t = r.get("created_at")
                    if t is not None:
                        k = t.strftime("%H:00")
                        hourly_jobs[k] = hourly_jobs.get(k, 0) + 1
                cur.execute(
                    "SELECT timestamp FROM results WHERE timestamp >= %s",
                    (since_24h,),
                )
                for r in cur.fetchall():
                    t = r.get("timestamp")
                    if t is not None:
                        k = t.strftime("%H:00")
                        hourly_results[k] = hourly_results.get(k, 0) + 1
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        # Be honest rather than crash the public route.
        return {
            "generated_at": _iso_utc(now),
            "show_names": show_names,
            "totals": {"searches_today": 0, "indexed_candidates": 0,
                       "matches_today": 0},
            "by_camera": [],
            "hourly_trend": [],
            "note": f"dashboard degraded: {exc}",
        }

    hours = sorted(set(hourly_jobs) | set(hourly_results))
    hourly_trend = [{"hour": h,
                     "searches": hourly_jobs.get(h, 0),
                     "matches": hourly_results.get(h, 0)} for h in hours]

    return {
        # UTC marker so the browser parses naive-UTC as UTC.
        "generated_at": _iso_utc(now),
        "show_names": show_names,
        "totals": {
            "searches_today": searches_today,
            "indexed_candidates": indexed_candidates,
            "matches_today": matches_today,
        },
        "by_camera": by_camera,
        "hourly_trend": hourly_trend,
    }


# Sample payload for the Settings UI / third-party integrators.
SAMPLE_INGEST_PAYLOAD = {
    "camera_id": "lobby-2",
    "camera_name": "Lobby East",
    "object_type": "person",
    "score": 0.84,
    "timestamp": "2026-06-20T14:30:00Z",
    "label": "subject-of-interest",
    "source": "edge-reid",
}


def ingest(payload: dict) -> dict:
    """Record an external sighting/match into the SS `results` table.

    SS ingest is less natural than for live scenarios — it has no per-frame event
    feed. We treat a posted payload as an external "sighting" and store it as a
    result row (job_id NULL) so it shows up in reports + the public dashboard,
    tagged source="external:...". Aggregate-safe: no image bytes are accepted."""
    camera_id = payload.get("camera_id")
    if not camera_id:
        return {"ok": False, "detail": "camera_id is required"}

    import uuid
    result_id = str(uuid.uuid4())
    object_type = str(payload.get("object_type") or "person")
    ts_raw = payload.get("timestamp")
    ts = _utcnow()
    if ts_raw:
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:  # noqa: BLE001
            ts = _utcnow()

    source = payload.get("source") or payload.get("camera_name") or camera_id
    record = {
        "result_id": result_id,
        "camera_id": str(camera_id),
        "object_type": object_type,
        "timestamp": _iso_utc(ts),
        "score": payload.get("score"),
        "label": payload.get("label"),
        "source": f"external:{source}",
    }

    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO results
                        (result_id, job_id, camera_id, object_type, timestamp,
                         thumb_path, payload_json)
                    VALUES (%s, NULL, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (result_id) DO NOTHING
                    """,
                    (result_id, str(camera_id), object_type, ts, "",
                     json.dumps(record, default=str)),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"ingest failed: {exc}"}

    # Aggregate-safe realtime notification.
    bus.publish({
        "event_id": result_id,
        "event_type": "sighting",
        "camera_id": str(camera_id),
        "label": object_type,
        "confidence": payload.get("score"),
        "triggered_at": _iso_utc(ts),
    })
    return {"ok": True, "event_id": result_id, "object_type": object_type}
