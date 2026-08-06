"""The four operator reports (client spec) + CSV/Excel export.

  1. Attendance      — per person: First-In, Last-Out, Duration (per day in range).
  2. Group           — per group: Headcount, Attendance Compliance %.
  3. Entry/Exit Mismatch — transit sessions: unpaired (open/overdue) vs resolved.
  4. Unknown Attempts — face_unknown events: count + snapshots.

Each report has a JSON endpoint (for the UI table) and the same data is exportable as
CSV or XLSX via ?format=csv|xlsx. The four are deliberately fixed — the old generic
"summary" stays for back-compat but the UI uses these.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import and_, func, select

import config
from db import session
from db.models import FRSAttendance, FRSEvent, FRSGroup, FRSPerson, TransitSession
from deps import require_service_token, allowed_camera_ids
from schemas import iso, naive

router = APIRouter(tags=["reports"])

REPORTS = ("attendance", "group", "mismatch", "unknown")

_SAFE = re.compile(r"^[A-Za-z0-9\-_]+$")


def _camera_names() -> dict:
    """camera_id → friendly name (cached). Reuses the public dashboard resolver."""
    try:
        from routers.public import _camera_names as _cn
        return _cn()
    except Exception:  # noqa: BLE001
        return {}


def _snapshot_file(value: str) -> Optional[Path]:
    """Resolve a stored snapshot reference (a '/snapshot?key=live:<id>' path, a bare
    'live:<id>' key, or a relative photo storage_key) to an on-disk image path, or
    None. Used to embed the actual image into XLSX exports."""
    if not value:
        return None
    key = value
    if value.startswith("/snapshot") or value.startswith("http"):
        q = parse_qs(urlparse(value).query)
        key = (q.get("key") or [""])[0]
    for prefix in ("live:", "ingest:"):
        if key.startswith(prefix):
            name = key[len(prefix):]
            if not _SAFE.match(name):
                return None
            p = config.DATA_PATH / "snapshots" / f"{name}.jpg"
            return p if p.exists() else None
    # else treat as a relative path under DATA_PATH (best effort, no traversal)
    if ".." in key or key.startswith("/"):
        return None
    p = config.DATA_PATH / key
    return p if p.exists() else None


# ── export helpers ─────────────────────────────────────────────────────────
def _csv(columns: list[str], rows: list[dict]) -> Response:
    # CSV is plain text — it can't EMBED an image. Instead of dropping the snapshot,
    # emit a "snapshot" column holding a present/absent marker (the actual picture is
    # in the XLSX export). Keeps the column so the CSV isn't missing it.
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        out = {c: r.get(c, "") for c in columns}
        if "snapshot" in columns:
            out["snapshot"] = "yes" if r.get("snapshot") else ""
        w.writerow(out)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=report.csv"})


def _xlsx(columns: list[str], rows: list[dict], title: str = "Report",
          charts: Optional[dict] = None) -> Response:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    has_snap = "snapshot" in columns
    ws.append([c.replace("_", " ").title() for c in columns])
    for c in ws[1]:
        c.font = Font(bold=True)

    THUMB = 56    # px — displayed thumbnail size
    ENCODE = 112  # px — stored image size (2x display for sharpness)

    def _thumb(src) -> Optional[io.BytesIO]:
        """Re-encode a snapshot to a small JPEG for embedding. Embedding the
        original full-resolution bytes made a 2000-row report ~44 MB — far past
        any mail attachment limit; ~112px JPEGs keep it a few MB."""
        try:
            from PIL import Image as PILImage
            im = PILImage.open(src).convert("RGB")
            im.thumbnail((ENCODE, ENCODE))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=72)
            buf.seek(0)
            return buf
        except Exception:  # noqa: BLE001
            return None

    for ri, r in enumerate(rows, start=2):
        ws.append([("" if c == "snapshot" else r.get(c, "")) for c in columns])
        if not has_snap:
            continue
        src = _snapshot_file(r.get("snapshot") or "")
        if not src:
            continue
        try:
            small = _thumb(src)
            img = XLImage(small) if small is not None else XLImage(str(src))
            img.width = img.height = THUMB
            col_letter = get_column_letter(columns.index("snapshot") + 1)
            ws.row_dimensions[ri].height = THUMB * 0.78  # pt
            ws.add_image(img, f"{col_letter}{ri}")
        except Exception:  # noqa: BLE001
            pass

    if has_snap:
        ws.column_dimensions[get_column_letter(columns.index("snapshot") + 1)].width = 10
    for c in ws[1]:
        c.alignment = Alignment(vertical="center")

    # Optional "Charts" sheet: a bar chart (e.g. working hours per person) and a
    # pie chart (e.g. regular vs overtime split). Data is written on the sheet so
    # the charts stay live/editable inside Excel.
    if charts:
        from openpyxl.chart import BarChart, PieChart, Reference

        cs = wb.create_sheet("Charts")
        bar = charts.get("bar")
        if bar and bar.get("categories"):
            cs["A1"] = bar.get("cat_label", "Category")
            cs["B1"] = bar.get("value_label", "Value")
            cs["A1"].font = cs["B1"].font = Font(bold=True)
            for i, (cat, val) in enumerate(zip(bar["categories"], bar["values"]), start=2):
                cs[f"A{i}"] = cat
                cs[f"B{i}"] = round(float(val), 2)
            n = len(bar["categories"])
            ch = BarChart()
            ch.type = "col"
            ch.title = bar.get("title", "Bar")
            ch.y_axis.title = bar.get("value_label", "Value")
            ch.height, ch.width = 9, max(14, min(30, 2 + n * 1.2))
            ch.add_data(Reference(cs, min_col=2, min_row=1, max_row=n + 1), titles_from_data=True)
            ch.set_categories(Reference(cs, min_col=1, min_row=2, max_row=n + 1))
            ch.legend = None
            cs.add_chart(ch, "D2")
        pie = charts.get("pie")
        if pie and pie.get("labels"):
            base = (len(bar["categories"]) + 3) if (bar and bar.get("categories")) else 1
            cs[f"A{base}"] = "Segment"
            cs[f"B{base}"] = pie.get("value_label", "Value")
            cs[f"A{base}"].font = cs[f"B{base}"].font = Font(bold=True)
            for i, (lab, val) in enumerate(zip(pie["labels"], pie["values"]), start=base + 1):
                cs[f"A{i}"] = lab
                cs[f"B{i}"] = round(float(val), 2)
            n = len(pie["labels"])
            pc = PieChart()
            pc.title = pie.get("title", "Pie")
            pc.height = pc.width = 9
            pc.add_data(Reference(cs, min_col=2, min_row=base, max_row=base + n), titles_from_data=True)
            pc.set_categories(Reference(cs, min_col=1, min_row=base + 1, max_row=base + n))
            cs.add_chart(pc, "D22")
        cs.column_dimensions["A"].width = 28

    bio = io.BytesIO()
    wb.save(bio)
    return Response(
        bio.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=report.xlsx"})


def _respond(columns, rows, fmt, title, charts: Optional[dict] = None):
    fmt = (fmt or "json").lower()
    if fmt == "csv":
        return _csv(columns, rows)
    if fmt in ("xlsx", "excel"):
        return _xlsx(columns, rows, title, charts=charts)
    return JSONResponse({"columns": columns, "items": rows, "total": len(rows)})


def _fmt_duration(seconds: Optional[float]) -> str:
    if not seconds or seconds < 0:
        return "—"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


# Report display timezone — timestamps are stored naive-UTC; the raw ISO strings
# ("2026-07-24T02:28:04.163523+00:00") are unreadable on a client report. Render
# them in the site's local timezone, human-formatted.
try:
    from zoneinfo import ZoneInfo
    _REPORT_TZ = ZoneInfo(getattr(config, "FRS_REPORT_TZ", None) or "Asia/Kolkata")
except Exception:  # noqa: BLE001
    _REPORT_TZ = None


def _fmt_ts(dt) -> str:
    """Naive-UTC datetime → '24-07-2026 07:58 AM' in the report timezone."""
    if not dt:
        return "—"
    try:
        from datetime import timezone as _tz
        aware = dt.replace(tzinfo=_tz.utc) if dt.tzinfo is None else dt
        local = aware.astimezone(_REPORT_TZ) if _REPORT_TZ else aware
        return local.strftime("%d-%m-%Y %I:%M %p")
    except Exception:  # noqa: BLE001
        return iso(dt) or "—"


# ── 1. Attendance: First-In, Last-Out, Duration ────────────────────────────
# Standard working day (hours). In→out beyond this counts as overtime.
STD_WORK_HOURS = float(getattr(config, "FRS_STD_WORK_HOURS", 9.0))


@router.get("/reports/attendance")
def report_attendance(day_from: str = Query(...), day_to: str = Query(...),
                      format: str = Query("json"),
                      _: None = Depends(require_service_token),
                      allowed: Optional[list[str]] = Depends(allowed_camera_ids)) -> Response:
    columns = ["snapshot", "day", "employee_id", "person_name", "group", "department",
               "designation", "first_in", "last_out", "duration", "overtime"]
    with session() as s:
        conds = [FRSAttendance.day_key >= day_from, FRSAttendance.day_key <= day_to]
        if allowed is not None:
            if not allowed:
                return _respond(columns, [], format, "Attendance")
            conds.append(FRSAttendance.camera_id.in_(allowed))
        stmt = (select(
            FRSAttendance.day_key, FRSAttendance.person_id, FRSPerson.full_name,
            FRSAttendance.check_in_at, FRSAttendance.check_out_at,
            FRSAttendance.check_in_snapshot, FRSAttendance.check_out_snapshot,
            FRSPerson.external_id, FRSPerson.department, FRSPerson.designation,
            FRSGroup.name,
        ).outerjoin(FRSPerson, FRSPerson.id == FRSAttendance.person_id)
         .outerjoin(FRSGroup, FRSGroup.id == FRSPerson.group_id)
         .where(and_(*conds))
         .order_by(FRSAttendance.day_key.desc(), FRSPerson.full_name))

        rows = []
        std_s = STD_WORK_HOURS * 3600.0
        person_hours: dict[str, float] = {}      # person -> total worked hours (range)
        total_reg = 0.0                          # regular hours (<= std) across range
        total_ot = 0.0                           # overtime hours across range
        for (day, pid, name, cin, cout, cin_snap, cout_snap,
             emp_id, dept, desig, group_name) in s.execute(stmt).all():
            last = cout or cin
            dur = (last - cin).total_seconds() if (cin and last) else None
            ot = max(0.0, dur - std_s) if dur else 0.0
            pname = name or (f"Person {str(pid)[:8]}" if pid else "Unknown")
            rows.append({
                "snapshot": cin_snap or cout_snap or "",
                "day": day,
                "employee_id": emp_id or "—",
                "person_name": pname,
                "group": group_name or "—",
                "department": dept or "—",
                "designation": desig or "—",
                "first_in": _fmt_ts(cin), "last_out": _fmt_ts(cout or cin),
                "duration": _fmt_duration(dur),
                "overtime": _fmt_duration(ot) if ot > 0 else "—",
            })
            if dur:
                person_hours[pname] = person_hours.get(pname, 0.0) + dur / 3600.0
                total_ot += ot / 3600.0
                total_reg += min(dur, std_s) / 3600.0

    # XLSX gets a Charts sheet: working hours per person (bar) + regular-vs-overtime (pie).
    top = sorted(person_hours.items(), key=lambda kv: kv[1], reverse=True)[:20]
    charts = {
        "bar": {
            "title": f"Working hours per person ({day_from} → {day_to})",
            "cat_label": "Person", "value_label": "Hours",
            "categories": [k for k, _ in top], "values": [v for _, v in top],
        },
        "pie": {
            "title": f"Regular vs overtime hours (> {STD_WORK_HOURS:g}h/day)",
            "value_label": "Hours",
            "labels": ["Regular", "Overtime"], "values": [total_reg, total_ot],
        },
    } if person_hours else None
    return _respond(columns, rows, format, "Attendance", charts=charts)


# ── 2. Group: Headcount, Attendance Compliance ─────────────────────────────
@router.get("/reports/group")
def report_group(day_from: str = Query(...), day_to: str = Query(...),
                 format: str = Query("json"),
                 _: None = Depends(require_service_token)) -> Response:
    columns = ["group", "headcount", "present", "compliance_pct"]
    with session() as s:
        # Total enrolled per group (headcount).
        head = dict(s.execute(
            select(FRSPerson.group_id, func.count())
            .where(FRSPerson.group_id.isnot(None))
            .group_by(FRSPerson.group_id)).all())
        # Distinct persons in this group seen at least once in range (present).
        present_rows = s.execute(
            select(FRSPerson.group_id, func.count(func.distinct(FRSAttendance.person_id)))
            .join(FRSPerson, FRSPerson.id == FRSAttendance.person_id)
            .where(and_(FRSAttendance.day_key >= day_from, FRSAttendance.day_key <= day_to,
                        FRSPerson.group_id.isnot(None)))
            .group_by(FRSPerson.group_id)).all()
        present = dict(present_rows)
        groups = s.execute(select(FRSGroup.id, FRSGroup.name)).all()
        rows = []
        for gid, gname in groups:
            hc = int(head.get(gid, 0))
            pr = int(present.get(gid, 0))
            comp = round(100.0 * pr / hc, 1) if hc else 0.0
            rows.append({"group": gname, "headcount": hc, "present": pr,
                         "compliance_pct": comp})
        rows.sort(key=lambda r: r["headcount"], reverse=True)
    return _respond(columns, rows, format, "Group")


# ── 3. Entry/Exit Mismatch: unpaired vs resolved ───────────────────────────
@router.get("/reports/mismatch")
def report_mismatch(day_from: str = Query(...), day_to: str = Query(...),
                    format: str = Query("json"),
                    _: None = Depends(require_service_token)) -> Response:
    columns = ["snapshot", "person_name", "group", "entry_time", "exit_time", "status"]
    if "T" in day_from or "T" in day_to:
        start = naive(datetime.fromisoformat(day_from)) if "T" in day_from else naive(datetime.fromisoformat(day_from + "T00:00:00"))
        end = naive(datetime.fromisoformat(day_to)) if "T" in day_to else naive(datetime.fromisoformat(day_to + "T23:59:59"))
    else:
        # Plain day strings are the operator's LOCAL days — convert to UTC bounds.
        from schemas import local_day_bounds
        start, end = local_day_bounds(day_from, day_to)
    with session() as s:
        stmt = (select(TransitSession, FRSPerson.full_name, FRSGroup.name)
                .outerjoin(FRSPerson, FRSPerson.id == TransitSession.person_id)
                .outerjoin(FRSGroup, FRSGroup.id == FRSPerson.group_id)
                .where(and_(TransitSession.started_at >= start, TransitSession.started_at <= end))
                .order_by(TransitSession.started_at.desc()))
        rows = []
        for sess, name, group_name in s.execute(stmt).all():
            attrs = sess.attributes or {}
            # closed = resolved (paired entry+exit); open/overdue = unpaired/unresolved.
            if sess.status == "closed":
                status = "Resolved"
            elif sess.status == "overdue":
                status = "Unresolved (overdue)"
            else:
                status = "Unpaired (no exit)"
            rows.append({
                "snapshot": attrs.get("entry_snapshot") or attrs.get("face_snapshot")
                or attrs.get("snapshot") or "",
                "person_name": name or attrs.get("person_name")
                or (f"Person {str(sess.person_id)[:8]}" if sess.person_id else "Unknown"),
                "group": group_name or "—",
                "entry_time": _fmt_ts(sess.started_at),
                "exit_time": _fmt_ts(sess.ended_at) if sess.ended_at else "—",
                "status": status,
            })
    return _respond(columns, rows, format, "Entry-Exit Mismatch")


# ── 4. Unknown Attempts: count + snapshots ─────────────────────────────────
@router.get("/reports/unknown")
def report_unknown(day_from: str = Query(...), day_to: str = Query(...),
                   format: str = Query("json"),
                   _: None = Depends(require_service_token),
                   allowed: Optional[list[str]] = Depends(allowed_camera_ids)) -> Response:
    # "confidence" here is the DETECTOR confidence (a face was found) — the match score
    # is always 0 on an Unknown, so showing that read as a confusing "0%".
    columns = ["snapshot", "time", "camera", "detected_pct"]
    if "T" in day_from or "T" in day_to:
        start = naive(datetime.fromisoformat(day_from)) if "T" in day_from else naive(datetime.fromisoformat(day_from + "T00:00:00"))
        end = naive(datetime.fromisoformat(day_to)) if "T" in day_to else naive(datetime.fromisoformat(day_to + "T23:59:59"))
    else:
        from schemas import local_day_bounds
        start, end = local_day_bounds(day_from, day_to)
    cam_names = _camera_names()
    with session() as s:
        conds = [FRSEvent.event_type == "face_unknown",
                 FRSEvent.triggered_at >= start, FRSEvent.triggered_at <= end]
        if allowed is not None:
            if not allowed:
                return _respond(columns, [], format, "Unknown Attempts")
            conds.append(FRSEvent.camera_id.in_(allowed))
        stmt = (select(FRSEvent).where(and_(*conds))
                .order_by(FRSEvent.triggered_at.desc()).limit(2000))
        evs = s.execute(stmt).scalars().all()
        rows = []
        for e in evs:
            attrs = e.attributes or {}
            # Prefer the stored detector confidence; fall back to the event confidence
            # only if it's non-zero (older rows had no det_confidence attr).
            det = attrs.get("det_confidence")
            if det is None:
                det = float(e.confidence or 0.0)
            rows.append({
                "snapshot": attrs.get("face_snapshot") or e.snapshot_path or "",
                "time": _fmt_ts(e.triggered_at),
                "camera": attrs.get("camera_name") or cam_names.get(str(e.camera_id))
                or (str(e.camera_id)[:8] if e.camera_id else "—"),
                "detected_pct": round(float(det) * 100, 1),
            })
    # The UI also wants a total count up top — include it in JSON; exports list rows.
    if (format or "json").lower() == "json":
        return JSONResponse({"columns": columns, "items": rows, "total": len(rows)})
    return _respond(columns, rows, format, "Unknown Attempts")
