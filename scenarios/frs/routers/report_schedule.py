"""Scheduled reports: CRUD + a background scheduler that, at each schedule's due
time, generates one of the four reports, emails it to the recipients, and stores the
file under DATA_PATH/reports for in-system download.

Kept dependency-light: a single daemon thread polls the schedules table once a minute
and fires anything due (no celery/cron). Email via stdlib smtplib.
"""
from __future__ import annotations

import logging
import smtplib
import threading
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select

import config
from db import session
from db.models import ReportRun, ReportSchedule
from deps import require_service_token
from schemas import iso

logger = logging.getLogger("frs.report_schedule")
router = APIRouter(tags=["reports"])

_VALID_REPORTS = {"attendance", "group", "mismatch", "unknown"}
_VALID_FREQ = {"daily", "weekly", "monthly"}


# ── generate a report file (reuses the four report builders) ───────────────
def _build_report_file(report: str, fmt: str, day_from: str, day_to: str) -> tuple[Path, int]:
    """Run the report function with format=fmt, write the bytes to REPORTS_DIR, and
    return (path, row_count)."""
    from routers import reports4
    fn = {
        "attendance": reports4.report_attendance,
        "group": reports4.report_group,
        "mismatch": reports4.report_mismatch,
        "unknown": reports4.report_unknown,
    }[report]
    # Call the endpoint function directly (no auth dep — internal). allowed=None so it
    # isn't camera-scoped for the scheduled/system run.
    kwargs = dict(day_from=day_from, day_to=day_to, format=fmt, _=None)
    if report in ("attendance", "unknown"):
        kwargs["allowed"] = None
    resp = fn(**kwargs)  # Response (csv/xlsx bytes)
    body = resp.body if hasattr(resp, "body") else b""
    # Count rows: re-run as json for the count (cheap).
    json_kwargs = dict(kwargs); json_kwargs["format"] = "json"
    jresp = fn(**json_kwargs)
    import json as _json
    rows = 0
    try:
        rows = _json.loads(jresp.body).get("total", 0)
    except Exception:  # noqa: BLE001
        pass
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = "xlsx" if fmt in ("xlsx", "excel") else "csv"
    stamp = day_to.replace(":", "").replace("-", "")
    fname = f"{report}_{stamp}_{int(time.time())}.{ext}"
    path = config.REPORTS_DIR / fname
    path.write_bytes(body)
    return path, rows


_SMTP_CACHE: dict = {"at": 0.0, "conf": None}


def _smtp_settings() -> Optional[dict]:
    """Effective SMTP settings. FRS_SMTP_* env wins when set; otherwise pull the
    operator-configured SMTP from nvr's Settings → Notifications via the internal
    API (service-token), cached for 60s. Returns None when nothing is configured."""
    if config.SMTP_HOST:
        return {"host": config.SMTP_HOST, "port": config.SMTP_PORT,
                "username": config.SMTP_USER, "password": config.SMTP_PASSWORD,
                "use_tls": config.SMTP_TLS, "use_ssl": False,
                "from_email": config.SMTP_FROM}
    now = time.time()
    if _SMTP_CACHE["conf"] is not None and now - _SMTP_CACHE["at"] < 60:
        return _SMTP_CACHE["conf"]
    try:
        import requests
        resp = requests.get(
            f"{config.VIZOR_BASE_URL}/ai/internal/smtp",
            headers={"X-Vizor-Service-Token": config.VIZOR_SERVICE_TOKEN,
                     "X-Vizor-Scenario": config.SCENARIO_SLUG},
            timeout=10)
        resp.raise_for_status()
        c = resp.json()
        conf = None
        if c.get("host"):
            frm = c.get("from_email") or c.get("username") or "noreply@vizor.local"
            if c.get("from_name"):
                frm = f'{c["from_name"]} <{frm}>'
            conf = {"host": c["host"], "port": int(c.get("port") or 587),
                    "username": c.get("username") or "",
                    "password": c.get("password") or "",
                    "use_tls": bool(c.get("use_tls", True)),
                    "use_ssl": bool(c.get("use_ssl", False)),
                    "from_email": frm}
        _SMTP_CACHE.update(at=now, conf=conf)
        return conf
    except Exception as e:  # noqa: BLE001
        logger.warning("[report-schedule] backend smtp fetch failed: %s", e)
        return _SMTP_CACHE["conf"]


# Most providers cap attachments at 25 MB (Gmail) — stay under it including the
# ~33% base64 overhead. Oversized reports are emailed as a notice instead (the
# file stays downloadable from the Reports page).
_MAX_ATTACH_MB = 18.0
# Large attachments upload slowly (a 6 MB report took ~70s at SMCC) — the old
# 30s timeout killed the send mid-upload ("Server not connected").
_SMTP_TIMEOUT_S = 180


def _send_email(recipients: list[str], subject: str, body_text: str,
                attachment: Path) -> bool:
    conf = _smtp_settings()
    if not conf or not recipients:
        # Loud skip — a silently-empty SMTP config looked like "email off" in the
        # UI for days before anyone noticed. Say WHY nothing was sent.
        logger.warning("[report-schedule] email skipped for %r: %s", subject,
                       "no SMTP configured (Settings → Notifications)" if not conf
                       else "no recipients")
        return False
    try:
        msg = EmailMessage()
        msg["From"] = conf["from_email"]
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        data = attachment.read_bytes()
        if len(data) > _MAX_ATTACH_MB * 1024 * 1024:
            size_mb = len(data) / (1024 * 1024)
            msg.set_content(
                f"{body_text}\n\nThe report file ({attachment.name}, "
                f"{size_mb:.0f} MB) exceeds the {_MAX_ATTACH_MB:.0f} MB email "
                f"attachment limit, so it is not attached. Download it from the "
                f"FRS Reports page (Recent files).")
            logger.warning("[report-schedule] %s is %.0f MB — emailing notice "
                           "without the attachment", attachment.name, size_mb)
        else:
            msg.set_content(body_text)
            sub = "csv" if attachment.suffix == ".csv" else \
                  "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            msg.add_attachment(data, maintype="application", subtype=sub,
                               filename=attachment.name)
    except Exception as e:  # noqa: BLE001
        logger.warning("[report-schedule] email build failed: %s", e)
        return False

    cls = smtplib.SMTP_SSL if conf.get("use_ssl") else smtplib.SMTP
    for attempt in (1, 2):
        try:
            with cls(conf["host"], conf["port"], timeout=_SMTP_TIMEOUT_S) as smtp:
                if conf.get("use_tls") and not conf.get("use_ssl"):
                    smtp.starttls()
                if conf.get("username"):
                    smtp.login(conf["username"], conf["password"])
                smtp.send_message(msg)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[report-schedule] email failed (attempt %d/2): %s",
                           attempt, e)
    return False


def _run_schedule(sched: ReportSchedule) -> ReportRun:
    """Generate + email + persist one report for a schedule (or manual run)."""
    from schemas import local_date
    today = local_date()
    day_to = today.strftime("%Y-%m-%d")
    day_from = (today - timedelta(days=max(0, sched.range_days - 1))).strftime("%Y-%m-%d")
    path, rows = _build_report_file(sched.report, sched.fmt, day_from, day_to)
    recipients = [r.strip() for r in (sched.recipients or "").split(",") if r.strip()]
    ok = _send_email(
        recipients,
        subject=f"[FRS] {sched.name} ({day_from}..{day_to})",
        body_text=f"Attached: {sched.report} report for {day_from} to {day_to} "
                  f"({rows} rows).",
        attachment=path) if recipients else None
    run = ReportRun(schedule_id=sched.id, report=sched.report, fmt=sched.fmt,
                    filename=path.name, path=str(path),
                    emailed_to=",".join(recipients) or None, email_ok=ok, rows=rows)
    with session() as s:
        s.add(run)
        live = s.get(ReportSchedule, sched.id)
        if live:
            live.last_run_at = datetime.utcnow()
            live.next_run_at = _compute_next(live)
        s.commit()
        s.refresh(run)
    return run


def _compute_next(sched: ReportSchedule, now: Optional[datetime] = None) -> datetime:
    """Next fire time as naive-UTC. at_time is the operator's SITE-LOCAL wall
    clock (e.g. 18:00 IST), converted here to UTC for the scheduler compare."""
    from datetime import timezone as _tz
    from schemas import REPORT_TZ
    now = now or datetime.utcnow()
    try:
        hh, mm = (int(x) for x in sched.at_time.split(":"))
    except Exception:  # noqa: BLE001
        hh, mm = 8, 0
    if REPORT_TZ is not None:
        local_now = now.replace(tzinfo=_tz.utc).astimezone(REPORT_TZ)
        local_nxt = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if local_nxt <= local_now:
            local_nxt += timedelta(days=1)
        nxt = local_nxt.astimezone(_tz.utc).replace(tzinfo=None)
    else:
        nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
    if sched.frequency == "weekly":
        # next same weekday (advance until >= now+1d already handled; bump 7 if today done)
        pass
    elif sched.frequency == "monthly":
        # crude: ~30d cadence anchored on the time of day
        if sched.last_run_at:
            nxt = max(nxt, sched.last_run_at + timedelta(days=30))
    return nxt


# ── scheduler thread ───────────────────────────────────────────────────────
class _Scheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._t: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._t is not None:
            return
        self._t = threading.Thread(target=self._loop, name="frs-report-scheduler", daemon=True)
        self._t.start()
        logger.info("[report-schedule] scheduler started")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = datetime.utcnow()
                with session() as s:
                    due = s.execute(select(ReportSchedule).where(
                        ReportSchedule.enabled.is_(True))).scalars().all()
                    fire = [sc for sc in due if (sc.next_run_at is None or sc.next_run_at <= now)]
                    # seed next_run_at for any schedule that has none yet
                    for sc in due:
                        if sc.next_run_at is None:
                            sc.next_run_at = _compute_next(sc, now)
                    s.commit()
                for sc in fire:
                    if sc.next_run_at is not None and sc.next_run_at > now:
                        continue  # was just seeded into the future
                    try:
                        _run_schedule(sc)
                        logger.info("[report-schedule] ran %s (%s)", sc.name, sc.report)
                    except Exception as e:  # noqa: BLE001
                        logger.exception("[report-schedule] run failed for %s: %s", sc.id, e)
            except Exception as e:  # noqa: BLE001
                logger.warning("[report-schedule] loop error: %s", e)
            self._stop.wait(60)


_SCHED = _Scheduler()


def start_report_scheduler() -> None:
    _SCHED.start()


# ── CRUD + manual run + download ───────────────────────────────────────────
def _sched_dict(s: ReportSchedule) -> dict:
    return {"id": s.id, "name": s.name, "report": s.report, "fmt": s.fmt,
            "frequency": s.frequency, "at_time": s.at_time, "range_days": s.range_days,
            "recipients": s.recipients, "enabled": s.enabled,
            "last_run_at": iso(s.last_run_at), "next_run_at": iso(s.next_run_at)}


@router.get("/report-schedules")
def list_schedules(_: None = Depends(require_service_token)) -> dict:
    with session() as s:
        rows = s.execute(select(ReportSchedule).order_by(ReportSchedule.created_at.desc())).scalars().all()
        return {"items": [_sched_dict(r) for r in rows]}


@router.post("/report-schedules")
def create_schedule(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    report = (body.get("report") or "").lower()
    if report not in _VALID_REPORTS:
        raise HTTPException(400, f"report must be one of {sorted(_VALID_REPORTS)}")
    freq = (body.get("frequency") or "daily").lower()
    if freq not in _VALID_FREQ:
        raise HTTPException(400, f"frequency must be one of {sorted(_VALID_FREQ)}")
    with session() as s:
        sc = ReportSchedule(
            name=str(body.get("name") or f"{report} report"),
            report=report, fmt=(body.get("fmt") or "xlsx").lower(),
            frequency=freq, at_time=str(body.get("at_time") or "08:00"),
            range_days=int(body.get("range_days") or 1),
            recipients=body.get("recipients"),
            enabled=bool(body.get("enabled", True)))
        sc.next_run_at = _compute_next(sc)
        s.add(sc); s.commit(); s.refresh(sc)
        return _sched_dict(sc)


@router.put("/report-schedules/{sid}")
def update_schedule(sid: str, body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        sc = s.get(ReportSchedule, sid)
        if not sc:
            raise HTTPException(404, "not found")
        for k in ("name", "report", "fmt", "frequency", "at_time", "recipients"):
            if k in body and body[k] is not None:
                setattr(sc, k, body[k])
        if "range_days" in body:
            sc.range_days = int(body["range_days"])
        if "enabled" in body:
            sc.enabled = bool(body["enabled"])
        sc.next_run_at = _compute_next(sc)
        s.commit(); s.refresh(sc)
        return _sched_dict(sc)


@router.delete("/report-schedules/{sid}")
def delete_schedule(sid: str, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        sc = s.get(ReportSchedule, sid)
        if sc:
            s.delete(sc); s.commit()
    return {"deleted": True}


@router.post("/report-schedules/{sid}/run")
def run_now(sid: str, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        sc = s.get(ReportSchedule, sid)
        if not sc:
            raise HTTPException(404, "not found")
    run = _run_schedule(sc)
    return {"run_id": run.id, "filename": run.filename, "rows": run.rows,
            "email_ok": run.email_ok}


@router.get("/report-runs")
def list_runs(limit: int = Query(50, ge=1, le=200), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        rows = s.execute(select(ReportRun).order_by(ReportRun.created_at.desc()).limit(limit)).scalars().all()
        return {"items": [{"id": r.id, "report": r.report, "fmt": r.fmt,
                           "filename": r.filename, "rows": r.rows,
                           "emailed_to": r.emailed_to, "email_ok": r.email_ok,
                           "created_at": iso(r.created_at)} for r in rows]}


@router.get("/report-runs/{rid}/download")
def download_run(rid: str, _: None = Depends(require_service_token)):
    with session() as s:
        r = s.get(ReportRun, rid)
        if not r:
            raise HTTPException(404, "not found")
        p = Path(r.path)
        if not p.exists():
            raise HTTPException(404, "file missing")
        media = "text/csv" if r.fmt == "csv" else \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return FileResponse(str(p), media_type=media, filename=r.filename)
