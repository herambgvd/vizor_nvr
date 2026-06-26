"""Scheduled PPE reports: CRUD + a background scheduler that generates one of the four
reports at its due time, emails it, and stores the file for in-system download.
Dependency-light: one daemon thread polls the schedules table each minute (FRS parity).
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
from fastapi.responses import FileResponse
from sqlalchemy import select

import config
from db import session
from db.models import ReportRun, ReportSchedule
from deps import require_service_token
from schemas import iso

logger = logging.getLogger("ppe.report_schedule")
router = APIRouter(tags=["reports"])

_VALID_REPORTS = {"compliance", "violations", "by_item", "worker"}
_VALID_FREQ = {"daily", "weekly", "monthly"}


def _build_report_file(report: str, fmt: str, day_from: str, day_to: str) -> tuple[Path, int]:
    from routers import reports4
    fn = {
        "compliance": reports4.report_compliance,
        "violations": reports4.report_violations,
        "by_item": reports4.report_by_item,
        "worker": reports4.report_worker,
    }[report]
    kwargs = dict(day_from=day_from, day_to=day_to, format=fmt, _=None, allowed=None)
    if report == "by_item":
        # by_item still takes allowed; all four accept allowed in this scenario.
        pass
    resp = fn(**kwargs)
    body = resp.body if hasattr(resp, "body") else b""
    import json as _json
    rows = 0
    try:
        jkw = dict(kwargs); jkw["format"] = "json"
        rows = _json.loads(fn(**jkw).body).get("total", 0)
    except Exception:  # noqa: BLE001
        pass
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = "xlsx" if fmt in ("xlsx", "excel") else "csv"
    fname = f"{report}_{day_to.replace('-', '')}_{int(time.time())}.{ext}"
    path = config.REPORTS_DIR / fname
    path.write_bytes(body)
    return path, rows


def _send_email(recipients: list[str], subject: str, body_text: str, attachment: Path) -> bool:
    if not config.SMTP_HOST or not recipients:
        return False
    try:
        msg = EmailMessage()
        msg["From"] = config.SMTP_FROM
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.set_content(body_text)
        sub = "csv" if attachment.suffix == ".csv" else \
              "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        msg.add_attachment(attachment.read_bytes(), maintype="application",
                           subtype=sub, filename=attachment.name)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
            if config.SMTP_TLS:
                smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[ppe report-schedule] email failed: %s", e)
        return False


def _compute_next(sched: ReportSchedule, now: Optional[datetime] = None) -> datetime:
    now = now or datetime.utcnow()
    try:
        hh, mm = (int(x) for x in sched.at_time.split(":"))
    except Exception:  # noqa: BLE001
        hh, mm = 8, 0
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    if sched.frequency == "monthly" and sched.last_run_at:
        nxt = max(nxt, sched.last_run_at + timedelta(days=30))
    return nxt


def _run_schedule(sched: ReportSchedule) -> ReportRun:
    today = datetime.utcnow().date()
    day_to = today.strftime("%Y-%m-%d")
    day_from = (today - timedelta(days=max(0, sched.range_days - 1))).strftime("%Y-%m-%d")
    path, rows = _build_report_file(sched.report, sched.fmt, day_from, day_to)
    recipients = [r.strip() for r in (sched.recipients or "").split(",") if r.strip()]
    ok = _send_email(recipients, f"[PPE] {sched.name} ({day_from}..{day_to})",
                     f"Attached: {sched.report} report {day_from}..{day_to} ({rows} rows).",
                     path) if recipients else None
    run = ReportRun(schedule_id=sched.id, report=sched.report, fmt=sched.fmt,
                    filename=path.name, path=str(path),
                    emailed_to=",".join(recipients) or None, email_ok=ok, rows=rows)
    with session() as s:
        s.add(run)
        live = s.get(ReportSchedule, sched.id)
        if live:
            live.last_run_at = datetime.utcnow()
            live.next_run_at = _compute_next(live)
        s.commit(); s.refresh(run)
    return run


class _Scheduler:
    def __init__(self) -> None:
        self._stop = threading.Event(); self._t: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._t is not None:
            return
        self._t = threading.Thread(target=self._loop, name="ppe-report-scheduler", daemon=True)
        self._t.start()
        logger.info("[ppe report-schedule] scheduler started")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = datetime.utcnow()
                with session() as s:
                    due = s.execute(select(ReportSchedule).where(
                        ReportSchedule.enabled.is_(True))).scalars().all()
                    fire = [sc for sc in due if (sc.next_run_at is None or sc.next_run_at <= now)]
                    for sc in due:
                        if sc.next_run_at is None:
                            sc.next_run_at = _compute_next(sc, now)
                    s.commit()
                for sc in fire:
                    if sc.next_run_at is not None and sc.next_run_at > now:
                        continue
                    try:
                        _run_schedule(sc)
                    except Exception as e:  # noqa: BLE001
                        logger.exception("[ppe report-schedule] run failed %s: %s", sc.id, e)
            except Exception as e:  # noqa: BLE001
                logger.warning("[ppe report-schedule] loop error: %s", e)
            self._stop.wait(60)


_SCHED = _Scheduler()


def start_report_scheduler() -> None:
    _SCHED.start()


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
            recipients=body.get("recipients"), enabled=bool(body.get("enabled", True)))
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
    return {"run_id": run.id, "filename": run.filename, "rows": run.rows, "email_ok": run.email_ok}


@router.get("/report-runs")
def list_runs(limit: int = Query(50, ge=1, le=200), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        rows = s.execute(select(ReportRun).order_by(ReportRun.created_at.desc()).limit(limit)).scalars().all()
        return {"items": [{"id": r.id, "report": r.report, "fmt": r.fmt, "filename": r.filename,
                           "rows": r.rows, "emailed_to": r.emailed_to, "email_ok": r.email_ok,
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
