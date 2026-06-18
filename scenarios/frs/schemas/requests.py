"""Pydantic request bodies for write routes.

Replaces raw `dict = Body(...)` so FastAPI validates types/required fields and
returns clean 422s, instead of 500s on bad input. Optional fields default to
None so PUT can patch-update.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PersonCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    external_id: Optional[str] = Field(default=None, max_length=100)
    group_id: Optional[str] = None
    category: str = Field(default="standard", max_length=20)
    priority: int = 0
    attributes: Optional[dict[str, Any]] = None


class PersonUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    external_id: Optional[str] = Field(default=None, max_length=100)
    group_id: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=20)
    priority: Optional[int] = None
    attributes: Optional[dict[str, Any]] = None


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    group_type: Optional[str] = Field(default=None, max_length=50)
    color_code: Optional[str] = Field(default=None, max_length=20)
    description: Optional[str] = None
    alert_sound: bool = False


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    group_type: Optional[str] = Field(default=None, max_length=50)
    color_code: Optional[str] = Field(default=None, max_length=20)
    description: Optional[str] = None
    alert_sound: Optional[bool] = None
