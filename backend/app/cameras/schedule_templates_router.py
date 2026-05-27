# =============================================================================
# Schedule Templates — saveable recording-schedule templates
# =============================================================================

import uuid
import logging
from datetime import datetime
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Text, JSON, DateTime, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.database import Base, get_db
from app.core.dependencies import require_permission, get_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedule-templates", tags=["Schedule Templates"])


# =============================================================================
# ORM Model
# =============================================================================

class ScheduleTemplate(Base):
    __tablename__ = "schedule_templates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    # grid shape: { "Mon": ["continuous", "off", ...x24], "Tue": [...], ... }
    grid = Column(JSON, nullable=False)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# =============================================================================
# Pydantic Schemas
# =============================================================================

class ScheduleTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    grid: Dict[str, Any]


class ScheduleTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    grid: Optional[Dict[str, Any]] = None


class ScheduleTemplateResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    grid: Dict[str, Any]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplyTemplateRequest(BaseModel):
    camera_ids: List[str]


# =============================================================================
# Helpers — default grid shapes
# =============================================================================

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _all_continuous() -> Dict[str, List[str]]:
    return {d: ["continuous"] * 24 for d in DAYS}


def _business_hours() -> Dict[str, List[str]]:
    """Mon-Fri 9-18 continuous, rest off."""
    grid = {}
    for i, day in enumerate(DAYS):
        if i < 5:  # Mon–Fri
            grid[day] = [
                "continuous" if 9 <= h < 18 else "off"
                for h in range(24)
            ]
        else:
            grid[day] = ["off"] * 24
    return grid


def _after_hours() -> Dict[str, List[str]]:
    """Inverse of business hours."""
    bh = _business_hours()
    return {
        day: ["continuous" if v == "off" else "off" for v in hours]
        for day, hours in bh.items()
    }


DEFAULT_TEMPLATES = [
    {
        "name": "24/7 Continuous",
        "description": "Record continuously around the clock every day",
        "grid": _all_continuous(),
    },
    {
        "name": "Business Hours (Mon-Fri 9-18)",
        "description": "Record only during business hours Monday through Friday",
        "grid": _business_hours(),
    },
    {
        "name": "After Hours",
        "description": "Record outside of business hours (evenings, nights, weekends)",
        "grid": _after_hours(),
    },
]


async def seed_default_templates(db: AsyncSession) -> None:
    """Ensure the three default templates exist. Idempotent."""
    for tpl in DEFAULT_TEMPLATES:
        existing = (
            await db.execute(
                select(ScheduleTemplate).where(ScheduleTemplate.name == tpl["name"])
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                ScheduleTemplate(
                    id=str(uuid.uuid4()),
                    name=tpl["name"],
                    description=tpl["description"],
                    grid=tpl["grid"],
                )
            )
    await db.commit()


# =============================================================================
# Routes
# =============================================================================

def _to_resp(t: ScheduleTemplate) -> ScheduleTemplateResponse:
    return ScheduleTemplateResponse(
        id=t.id,
        name=t.name,
        description=t.description,
        grid=t.grid,
        created_by=t.created_by,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("", response_model=List[ScheduleTemplateResponse])
async def list_templates(
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ScheduleTemplate).order_by(ScheduleTemplate.created_at))
    return [_to_resp(t) for t in result.scalars().all()]


@router.post("", response_model=ScheduleTemplateResponse, status_code=201)
async def create_template(
    data: ScheduleTemplateCreate,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (
        await db.execute(
            select(ScheduleTemplate).where(ScheduleTemplate.name == data.name)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Template with name '{data.name}' already exists")

    tpl = ScheduleTemplate(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        grid=data.grid,
        created_by=user["id"],
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return _to_resp(tpl)


@router.put("/{template_id}", response_model=ScheduleTemplateResponse)
async def update_template(
    template_id: str,
    data: ScheduleTemplateUpdate,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    tpl = (
        await db.execute(
            select(ScheduleTemplate).where(ScheduleTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Template not found")

    if data.name is not None:
        tpl.name = data.name
    if data.description is not None:
        tpl.description = data.description
    if data.grid is not None:
        tpl.grid = data.grid
    tpl.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(tpl)
    return _to_resp(tpl)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    tpl = (
        await db.execute(
            select(ScheduleTemplate).where(ScheduleTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Template not found")
    await db.delete(tpl)
    await db.commit()


@router.post("/{template_id}/apply")
async def apply_template(
    template_id: str,
    body: ApplyTemplateRequest,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Copy this template's grid into each listed camera's recording_schedule."""
    from app.cameras.models import Camera

    tpl = (
        await db.execute(
            select(ScheduleTemplate).where(ScheduleTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Template not found")

    applied = 0
    failed = []
    for cam_id in body.camera_ids:
        cam = (
            await db.execute(select(Camera).where(Camera.id == cam_id))
        ).scalar_one_or_none()
        if not cam:
            failed.append({"id": cam_id, "error": "not_found"})
            continue
        try:
            cam.recording_schedule = tpl.grid
            applied += 1
        except Exception as exc:
            failed.append({"id": cam_id, "error": str(exc)})

    await db.commit()
    return {"applied": applied, "failed": failed}
