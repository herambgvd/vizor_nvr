"""Password policy regex/length checks — uses SettingsService get_value mock."""
import pytest
from unittest.mock import AsyncMock, patch

from app.auth import password_policy


@pytest.mark.asyncio
async def test_short_password_rejected():
    async def fake_get_value(db, key, default):
        return {"password_min_length": "10",
                "password_require_uppercase": "false",
                "password_require_number": "false",
                "password_require_symbol": "false"}.get(key, default)
    with patch("app.settings.service.SettingsService.get_value", new=fake_get_value):
        errs = await password_policy.validate(None, "short")
        assert any("at least 10" in e for e in errs)


@pytest.mark.asyncio
async def test_full_policy():
    async def fake_get_value(db, key, default):
        return {"password_min_length": "8",
                "password_require_uppercase": "true",
                "password_require_number": "true",
                "password_require_symbol": "true"}.get(key, default)
    with patch("app.settings.service.SettingsService.get_value", new=fake_get_value):
        assert await password_policy.validate(None, "Goodpass1!") == []
        errs = await password_policy.validate(None, "alllower1")
        assert any("uppercase" in e for e in errs)
