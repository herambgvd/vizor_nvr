# =============================================================================
# Password policy enforcement (Phase 5.6)
# =============================================================================
#
# Policy values are read live from the settings table so the operator can
# tighten them without a restart. All keys default to safe values if missing.
#   password_min_length              (int, default 8)
#   password_require_uppercase       (bool, default true)
#   password_require_number          (bool, default true)
#   password_require_symbol          (bool, default false)
#   password_history_count           (int, default 0 — disabled)
#   password_max_age_days            (int, default 0 — never expires)
# =============================================================================

import re
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession


SYMBOLS = re.compile(r"[!@#$%^&*()_\-+={}\[\]|\\:;\"'<>,.?/~`]")


async def _settings(db: AsyncSession) -> dict:
    from app.settings.service import SettingsService
    return {
        "min_length": int(await SettingsService.get_value(db, "password_min_length", "8") or 8),
        "uppercase": (await SettingsService.get_value(db, "password_require_uppercase", "true")).lower() == "true",
        "number": (await SettingsService.get_value(db, "password_require_number", "true")).lower() == "true",
        "symbol": (await SettingsService.get_value(db, "password_require_symbol", "false")).lower() == "true",
        "history": int(await SettingsService.get_value(db, "password_history_count", "0") or 0),
        "max_age_days": int(await SettingsService.get_value(db, "password_max_age_days", "0") or 0),
    }


async def validate(db: AsyncSession, password: str) -> List[str]:
    """Return a list of human-readable failures. Empty list = OK."""
    p = await _settings(db)
    errs = []
    if len(password) < p["min_length"]:
        errs.append(f"must be at least {p['min_length']} characters")
    if p["uppercase"] and not any(c.isupper() for c in password):
        errs.append("must contain an uppercase letter")
    if p["number"] and not any(c.isdigit() for c in password):
        errs.append("must contain a number")
    if p["symbol"] and not SYMBOLS.search(password):
        errs.append("must contain a symbol")
    return errs


async def check_history(db: AsyncSession, user_id: str, new_password_hash: str) -> bool:
    """Return True if the password is *not* in the user's recent history."""
    from app.settings.service import SettingsService
    keep = int(await SettingsService.get_value(db, "password_history_count", "0") or 0)
    if keep <= 0:
        return True
    from sqlalchemy import text
    rows = (await db.execute(text("""
        SELECT password_hash FROM password_history
        WHERE user_id = :uid
        ORDER BY changed_at DESC LIMIT :k
    """), {"uid": user_id, "k": keep})).fetchall()
    return all(r[0] != new_password_hash for r in rows)


async def record_history(db: AsyncSession, user_id: str, password_hash: str):
    """Append a row to password_history so future changes can check against it."""
    from sqlalchemy import text
    import uuid
    await db.execute(text("""
        INSERT INTO password_history (id, user_id, password_hash, changed_at)
        VALUES (:id, :uid, :ph, CURRENT_TIMESTAMP)
    """), {"id": str(uuid.uuid4()), "uid": user_id, "ph": password_hash})
    # Auto-truncate rows beyond the configured history count to prevent unbounded growth
    from app.settings.service import SettingsService
    keep = int(await SettingsService.get_value(db, "password_history_count", "0") or 0)
    if keep > 0:
        await db.execute(text("""
            DELETE FROM password_history
            WHERE id NOT IN (
                SELECT id FROM password_history
                WHERE user_id = :uid
                ORDER BY changed_at DESC LIMIT :k
            )
            AND user_id = :uid
        """), {"uid": user_id, "k": keep})


async def expired(db: AsyncSession, password_changed_at: Optional[datetime]) -> bool:
    """True if max_age_days is configured and the password is older than that."""
    from app.settings.service import SettingsService
    max_age = int(await SettingsService.get_value(db, "password_max_age_days", "0") or 0)
    if max_age <= 0 or not password_changed_at:
        return False
    return password_changed_at < datetime.utcnow() - timedelta(days=max_age)
