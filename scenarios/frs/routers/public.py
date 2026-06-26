"""Public FRS dashboard — UNAUTHENTICATED, aggregate analytics only.

Gated by the public_dashboard_enabled toggle (FRS settings); returns 404 when
off so the surface simply doesn't exist. Exposes only AGGREGATE stats + a
realtime SSE stream — never snapshots or raw face images. Person names appear
only when the operator opts in (public_show_names).
"""
from __future__ import annotations

import json
import queue
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from db import session
from db.events import subscribe, unsubscribe
from db.models import FRSEvent, FRSGroup, FRSPerson, TransitSession
from db.settings_store import get_settings
from schemas import iso, utcnow

# How long after a recognition a person is still counted "present" on the floor.
PRESENCE_WINDOW_MIN = 15

router = APIRouter(prefix="/public", tags=["public"])


def _guard() -> dict:
    st = get_settings()
    if not st["public_dashboard_enabled"]:
        raise HTTPException(404, "not found")
    return st


# Camera id → friendly name, cached ~60s (the dashboard polls; don't hammer core).
_CAM_CACHE: dict = {"at": 0.0, "map": {}}


def _camera_names() -> dict:
    import time
    now = time.time()
    if now - _CAM_CACHE["at"] < 60 and _CAM_CACHE["map"]:
        return _CAM_CACHE["map"]
    names: dict = {}
    try:
        from live.manager import _fetch_cameras
        for c in _fetch_cameras():
            cid = c.get("camera_id") or c.get("device_id") or c.get("id")
            nm = c.get("camera_name") or c.get("name")
            if cid and nm:
                names[str(cid)] = nm
    except Exception:  # noqa: BLE001
        pass
    if names:
        _CAM_CACHE.update(at=now, map=names)
    return names


def _cam(cid, names) -> str:
    if not cid:
        return "—"
    return names.get(str(cid)) or (str(cid)[:8])


@router.get("/dashboard")
def public_dashboard() -> dict:
    """Aggregate FRS analytics for the public dashboard. No auth, no snapshots."""
    st = _guard()
    show_names = st["public_show_names"]
    now = utcnow()
    today = now.date()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with session() as s:
        def _count(*conds):
            q = select(func.count()).select_from(FRSEvent)
            for c in conds:
                q = q.where(c)
            return int(s.scalar(q) or 0)

        recognized = _count(FRSEvent.event_type == "face_recognized")
        recognized_today = _count(FRSEvent.event_type == "face_recognized",
                                  FRSEvent.triggered_at >= day_start)
        unknown_today = _count(FRSEvent.event_type == "face_unknown",
                               FRSEvent.triggered_at >= day_start)
        total_today = _count(FRSEvent.triggered_at >= day_start)
        enrolled_persons = int(s.scalar(select(func.count()).select_from(FRSPerson)) or 0)

        # Per-camera counts today.
        per_cam = s.execute(
            select(FRSEvent.camera_id, func.count())
            .where(FRSEvent.triggered_at >= day_start)
            .group_by(FRSEvent.camera_id)
        ).all()
        cam_names = _camera_names()
        by_camera = [{"camera_id": c or "unknown",
                      "camera_name": _cam(c, cam_names),
                      "count": int(n)} for c, n in per_cam]

        # Hourly trend (last 24h) — CONTINUOUS timeline: one bucket per hour for the
        # whole window (zero-filled) so the chart is a smooth 24h curve, not a few
        # sparse points that collapse into a flat/jagged line.
        win = now.replace(minute=0, second=0, microsecond=0)
        hours = [win - timedelta(hours=k) for k in range(23, -1, -1)]
        since = hours[0]
        rows = s.execute(
            select(FRSEvent.triggered_at)
            .where(FRSEvent.triggered_at >= since)
        ).all()
        counts: dict[str, int] = {}
        for (t,) in rows:
            if t is None:
                continue
            counts[t.strftime("%Y-%m-%d %H")] = counts.get(t.strftime("%Y-%m-%d %H"), 0) + 1
        hourly = [{
            "hour": hh.strftime("%H:00"),
            "ts": hh.isoformat() + "Z",
            "count": counts.get(hh.strftime("%Y-%m-%d %H"), 0),
        } for hh in hours]

        # Top recognised persons today (names only if opted in).
        top = []
        if show_names:
            tp = s.execute(
                select(FRSEvent.person_id, func.count())
                .where(FRSEvent.event_type == "face_recognized",
                       FRSEvent.triggered_at >= day_start,
                       FRSEvent.person_id.isnot(None))
                .group_by(FRSEvent.person_id)
                .order_by(func.count().desc())
                .limit(5)
            ).all()
            for pid, n in tp:
                p = s.get(FRSPerson, pid)
                top.append({"name": p.full_name if p else "—", "count": int(n)})

        # ── 1. Headcount present now + trend vs last hour ──────────────────
        # "Present" = distinct enrolled persons recognised within the window.
        win_start = now - timedelta(minutes=PRESENCE_WINDOW_MIN)
        prev_start = now - timedelta(minutes=2 * PRESENCE_WINDOW_MIN)

        def _present(since, until):
            q = (select(func.count(func.distinct(FRSEvent.person_id)))
                 .where(FRSEvent.event_type == "face_recognized",
                        FRSEvent.person_id.isnot(None),
                        FRSEvent.triggered_at >= since))
            if until is not None:
                q = q.where(FRSEvent.triggered_at < until)
            return int(s.scalar(q) or 0)

        present_now = _present(win_start, None)
        present_prev = _present(prev_start, win_start)
        headcount = {
            "present_now": present_now,
            "prev_window": present_prev,
            "trend": present_now - present_prev,  # +/- vs previous window
        }

        # ── 2. Group-wise headcount (present persons grouped by group) ─────
        gr_rows = s.execute(
            select(FRSGroup.name, FRSGroup.color_code,
                   func.count(func.distinct(FRSEvent.person_id)))
            .select_from(FRSEvent)
            .join(FRSPerson, FRSPerson.id == FRSEvent.person_id)
            .join(FRSGroup, FRSGroup.id == FRSPerson.group_id)
            .where(FRSEvent.event_type == "face_recognized",
                   FRSEvent.triggered_at >= win_start)
            .group_by(FRSGroup.name, FRSGroup.color_code)
            .order_by(func.count(func.distinct(FRSEvent.person_id)).desc())
        ).all()
        by_group = [{"group": g or "—", "color": c, "present": int(n)}
                    for g, c, n in gr_rows]

        # ── 3. Live violations ticker — spoof / overdue / alert-group hits ─
        # A violation is a spoof attempt, an overdue transit, or a recognition of a
        # person whose group is flagged as an alert group. Aggregate-safe fields only.
        viol_rows = s.execute(
            select(FRSEvent, FRSPerson.full_name, FRSGroup.name, FRSGroup.alert_sound)
            .outerjoin(FRSPerson, FRSPerson.id == FRSEvent.person_id)
            .outerjoin(FRSGroup, FRSGroup.id == FRSPerson.group_id)
            .where(FRSEvent.triggered_at >= now - timedelta(hours=6))
            .order_by(FRSEvent.triggered_at.desc())
            .limit(200)
        ).all()
        violations = []
        for ev, pname, gname, alert_group in viol_rows:
            et = ev.event_type
            if et == "spoof_detected":
                reason = "Spoof / liveness fail"
            elif et == "transit_overdue":
                reason = "Transit overdue"
            elif et == "face_recognized" and alert_group:
                reason = f"Alert group: {gname}"
            else:
                continue
            violations.append({
                "name": (pname or "Unknown") if show_names else "—",
                "group": gname or "—",
                "camera": _cam(ev.camera_id, cam_names),
                "reason": reason,
                "time": iso(ev.triggered_at),
            })
            if len(violations) >= 30:
                break

        # ── 4. Entry/Exit mismatch — open (unpaired) + overdue sessions ────
        mm_rows = s.execute(
            select(TransitSession, FRSPerson.full_name)
            .outerjoin(FRSPerson, FRSPerson.id == TransitSession.person_id)
            .where(TransitSession.status.in_(("open", "overdue")))
            .order_by(TransitSession.started_at.desc())
            .limit(30)
        ).all()
        mismatches = [{
            "name": (name or "Unknown") if show_names else "—",
            "entry_time": iso(sess.started_at),
            "status": "Overdue" if sess.status == "overdue" else "No exit yet",
        } for sess, name in mm_rows]
        mismatch_count = int(s.scalar(
            select(func.count()).select_from(TransitSession)
            .where(TransitSession.status.in_(("open", "overdue")))) or 0)

        # ── 5. Unknown persons — recent snapshots (blurred client-side) ────
        unk_rows = s.execute(
            select(FRSEvent)
            .where(FRSEvent.event_type == "face_unknown",
                   FRSEvent.triggered_at >= day_start)
            .order_by(FRSEvent.triggered_at.desc())
            .limit(24)
        ).scalars().all()
        unknowns = []
        for ev in unk_rows:
            attrs = ev.attributes or {}
            snap = attrs.get("face_snapshot") or ev.snapshot_path
            if not snap:
                continue
            unknowns.append({
                "snapshot": snap,           # frontend renders BLURRED for privacy
                "camera": ev.camera_id or "—",
                "time": iso(ev.triggered_at),
            })

    return {
        # Stamp +00:00 so the browser parses it as UTC, not local time.
        "generated_at": now.isoformat() + "Z",
        "show_names": show_names,
        "totals": {
            "recognized_all_time": recognized,
            "recognized_today": recognized_today,
            "unknown_today": unknown_today,
            "events_today": total_today,
            "enrolled_persons": enrolled_persons,
        },
        "by_camera": by_camera,
        "hourly_trend": hourly,
        "top_persons": top,
        # Enhanced public dashboard blocks:
        "headcount": headcount,          # 1. present now + trend vs last window
        "by_group": by_group,            # 2. group-wise headcount
        "violations": violations,        # 3. live violations ticker
        "mismatches": mismatches,        # 4. entry/exit mismatch panel
        "mismatch_count": mismatch_count,
        "unknowns": unknowns,            # 5. unknown snapshots (blur client-side)
    }


@router.get("/snapshot")
def public_snapshot(key: str):
    """Privacy-safe snapshot for the public dashboard: serves the face crop but
    HEAVILY BLURRED server-side, so the public surface never exposes an identifiable
    face. Only 'live:'/'ingest:' snapshot keys are allowed (never enrolled photos),
    and only while the public dashboard is enabled."""
    from fastapi import Query
    from fastapi.responses import Response
    import config
    _guard()
    # Resolve the key to an on-disk crop (same rule as the authed /snapshot).
    if not (key.startswith("live:") or key.startswith("ingest:")):
        raise HTTPException(404, "not found")
    name = key.split(":", 1)[1]
    if not all(c.isalnum() or c in "-_" for c in name) or "/" in name or ".." in name:
        raise HTTPException(404, "not found")
    path = config.DATA_PATH / "snapshots" / f"{name}.jpg"
    if not path.exists():
        raise HTTPException(404, "not found")
    try:
        import cv2
        import numpy as np
        img = cv2.imread(str(path))
        if img is None:
            raise ValueError("decode")
        # Pixelate (downscale→upscale) + blur — irreversible, identity-obscuring.
        h, w = img.shape[:2]
        small = cv2.resize(img, (max(1, w // 16), max(1, h // 16)), interpolation=cv2.INTER_LINEAR)
        img = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        img = cv2.GaussianBlur(img, (0, 0), sigmaX=8)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            raise ValueError("encode")
        return Response(buf.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=60"})
    except Exception:  # noqa: BLE001
        raise HTTPException(404, "not found")


@router.get("/stream")
def public_stream() -> StreamingResponse:
    """SSE realtime feed of new FRS events (aggregate-safe: type/camera/name/
    confidence only — no snapshots). Gated by the public toggle."""
    _guard()
    q = subscribe()

    def _gen():
        try:
            # Initial comment so the connection opens promptly.
            yield ": connected\n\n"
            while True:
                try:
                    item = q.get(timeout=20)
                    yield f"data: {json.dumps(item)}\n\n"
                except queue.Empty:
                    # Heartbeat keeps proxies from closing an idle stream.
                    yield ": ping\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
