"""Pydantic request bodies for write routes.

Replaces raw `dict = Body(...)` so FastAPI validates types/required fields and
returns clean 422s, instead of 500s on bad input. Optional fields default to
None so PUT can patch-update.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

# Validity window can be at most 6 months (~183 days).
_MAX_VALIDITY_DAYS = 183


class _PersonProfileFields(BaseModel):
    """Extended operator-entered profile fields, shared by create + update."""
    department: Optional[str] = Field(default=None, max_length=120)
    designation: Optional[str] = Field(default=None, max_length=120)   # "Profile" = role
    contact_number: Optional[str] = Field(default=None, max_length=40)
    date_of_joining: Optional[date] = None
    id_type: Optional[str] = Field(default=None, max_length=60)
    id_number: Optional[str] = Field(default=None, max_length=120)
    validity_start: Optional[date] = None
    validity_end: Optional[date] = None
    auto_remove: Optional[bool] = None

    @model_validator(mode="after")
    def _check_validity(self):
        s, e = self.validity_start, self.validity_end
        if s and e:
            if e < s:
                raise ValueError("validity_end must be on or after validity_start")
            if (e - s) > timedelta(days=_MAX_VALIDITY_DAYS):
                raise ValueError("validity window cannot exceed 6 months")
        if self.auto_remove and not e:
            raise ValueError("auto_remove requires a validity_end date")
        return self


class PersonCreate(_PersonProfileFields):
    full_name: str = Field(min_length=1, max_length=200)
    external_id: Optional[str] = Field(default=None, max_length=100)
    group_id: Optional[str] = None
    category: str = Field(default="standard", max_length=20)
    priority: int = 0
    attributes: Optional[dict[str, Any]] = None


class PersonUpdate(_PersonProfileFields):
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
