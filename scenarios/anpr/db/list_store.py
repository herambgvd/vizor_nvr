"""User-defined plate lists store + matcher.

PER-SCENARIO GLOBAL lists (one set of lists across all ANPR cameras). Each list
(anpr_list_def) carries an ACTION (alert/allow/log); plate entries belong to a
list. On each read the live worker calls `match_plate(normalized)` to tag the
read with the matched list + action and pick the event severity from the action
(alert -> high severity, the old blacklist behaviour). Plates are stored +
matched normalised (uppercase, A-Z0-9 only)."""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import func, select

from db import session
from db.models import ANPRListDef, ANPRPlateList
from schemas import utcnow

_NORM_RE = re.compile(r"[^A-Z0-9]")

# Recognised list actions. "alert" wins precedence on a multi-list match.
VALID_ACTIONS = ("alert", "allow", "log")


def normalize_plate(text: str) -> str:
    """Uppercase + strip everything that isn't A-Z/0-9. Single normalisation used
    everywhere (OCR output, list entries, matcher) so comparisons are exact."""
    return _NORM_RE.sub("", (text or "").upper())


def match_plate(plate: str, now=None) -> Optional[dict]:
    """Return the active list entry matching `plate` (already normalised), or None.

    Result: {entry_id, list_id, list_name, action, label}. An entry only matches
    inside its [valid_from, valid_to] window (NULL bounds = unbounded). Precedence:
    an `alert`-action list wins over the others (so a blacklist-style alert is
    never masked by an allow/log match); otherwise the first match wins."""
    norm = normalize_plate(plate)
    if not norm:
        return None
    now = now or utcnow()
    with session() as s:
        rows = s.execute(
            select(ANPRPlateList, ANPRListDef)
            .join(ANPRListDef, ANPRPlateList.list_id == ANPRListDef.id)
            .where(ANPRPlateList.plate == norm)
        ).all()
    best = None
    for entry, ldef in rows:
        if entry.valid_from is not None and now < entry.valid_from:
            continue
        if entry.valid_to is not None and now > entry.valid_to:
            continue
        hit = {
            "entry_id": entry.id,
            "list_id": ldef.id,
            "list_name": ldef.name,
            "action": ldef.action or "alert",
            "label": entry.label,
        }
        if hit["action"] == "alert":
            return hit  # alert takes precedence immediately
        best = best or hit
    return best


# ── list-def CRUD helpers ────────────────────────────────────────────────────
def _def_dict(d: ANPRListDef, entry_count: Optional[int] = None) -> dict:
    out = {
        "id": d.id,
        "name": d.name,
        "action": d.action,
        "color": d.color,
        "description": d.description,
        "created_at": d.created_at.isoformat() + "Z" if d.created_at else None,
    }
    if entry_count is not None:
        out["entry_count"] = int(entry_count)
    return out


def list_defs() -> list[dict]:
    """All list definitions with their entry counts, newest first."""
    with session() as s:
        counts = dict(
            s.execute(
                select(ANPRPlateList.list_id, func.count())
                .group_by(ANPRPlateList.list_id)
            ).all()
        )
        rows = s.execute(
            select(ANPRListDef).order_by(ANPRListDef.created_at.desc())
        ).scalars().all()
        return [_def_dict(d, counts.get(d.id, 0)) for d in rows]


def get_list_def(list_id: str) -> Optional[dict]:
    with session() as s:
        d = s.get(ANPRListDef, list_id)
        return _def_dict(d) if d else None


def find_list_def_by_name(name: str) -> Optional[dict]:
    with session() as s:
        d = s.execute(
            select(ANPRListDef).where(func.lower(ANPRListDef.name) == name.strip().lower())
        ).scalars().first()
        return _def_dict(d) if d else None


def create_list_def(name: str, action: str = "alert", color=None,
                    description=None) -> dict:
    """Create a new list. Raises ValueError on a blank or duplicate name, or an
    invalid action."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    action = (action or "alert").strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError("action must be one of alert, allow, log")
    with session() as s:
        dup = s.execute(
            select(ANPRListDef).where(func.lower(ANPRListDef.name) == name.lower())
        ).scalars().first()
        if dup:
            raise ValueError(f"a list named '{name}' already exists")
        d = ANPRListDef(name=name, action=action,
                        color=(color or None), description=(description or None))
        s.add(d)
        s.commit()
        s.refresh(d)
        return _def_dict(d, 0)


def update_list_def(list_id: str, *, name=None, action=None, color=None,
                    description=None) -> Optional[dict]:
    """Patch a list. Only provided fields change. Raises ValueError on a duplicate
    name or invalid action. Returns None if the list doesn't exist."""
    with session() as s:
        d = s.get(ANPRListDef, list_id)
        if not d:
            return None
        if name is not None:
            new_name = name.strip()
            if not new_name:
                raise ValueError("name cannot be blank")
            dup = s.execute(
                select(ANPRListDef).where(
                    func.lower(ANPRListDef.name) == new_name.lower(),
                    ANPRListDef.id != list_id,
                )
            ).scalars().first()
            if dup:
                raise ValueError(f"a list named '{new_name}' already exists")
            d.name = new_name
        if action is not None:
            act = action.strip().lower()
            if act not in VALID_ACTIONS:
                raise ValueError("action must be one of alert, allow, log")
            d.action = act
        if color is not None:
            d.color = color or None
        if description is not None:
            d.description = description or None
        s.commit()
        s.refresh(d)
        return _def_dict(d)


def delete_list_def(list_id: str) -> Optional[dict]:
    """Cascade-delete a list and all its plate entries. Returns
    {deleted_entries} on success, or None if the list doesn't exist."""
    with session() as s:
        d = s.get(ANPRListDef, list_id)
        if not d:
            return None
        n = s.execute(
            select(func.count()).select_from(ANPRPlateList)
            .where(ANPRPlateList.list_id == list_id)
        ).scalar() or 0
        s.execute(
            ANPRPlateList.__table__.delete().where(ANPRPlateList.list_id == list_id)
        )
        s.delete(d)
        s.commit()
        return {"deleted_entries": int(n)}
