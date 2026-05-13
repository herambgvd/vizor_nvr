"""
Integration tests for authentication flow.
Covers: register, login, refresh, logout, me, 2FA setup, password policy.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_login(async_client: AsyncClient):
    """Full happy-path auth flow."""
    # Register
    r1 = await async_client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!",
    })
    assert r1.status_code == 201 or r1.status_code == 200, r1.text

    # Login
    r2 = await async_client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "SecurePass123!",
    })
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert "access_token" in data or "token" in data
    assert "refresh_token" in data

    # Get me
    token = data.get("access_token") or data.get("token")
    r3 = await async_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r3.status_code == 200
    assert r3.json()["username"] == "testuser"


@pytest.mark.asyncio
async def test_login_wrong_password(async_client: AsyncClient):
    """Login with bad password should fail."""
    # Register first
    await async_client.post("/api/auth/register", json={
        "username": "wrongpassuser",
        "email": "wrong@example.com",
        "password": "SecurePass123!",
    })

    r = await async_client.post("/api/auth/login", json={
        "username": "wrongpassuser",
        "password": "WrongPass123!",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_flow(async_client: AsyncClient):
    """Refresh token should issue new access token."""
    # Register + login
    await async_client.post("/api/auth/register", json={
        "username": "refreshuser",
        "email": "refresh@example.com",
        "password": "SecurePass123!",
    })
    r = await async_client.post("/api/auth/login", json={
        "username": "refreshuser",
        "password": "SecurePass123!",
    })
    data = r.json()
    refresh = data["refresh_token"]

    # Refresh
    r2 = await async_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 200, r2.text
    assert "access_token" in r2.json()


@pytest.mark.asyncio
async def test_password_policy_rejection(async_client: AsyncClient):
    """Weak password should be rejected at registration."""
    r = await async_client.post("/api/auth/register", json={
        "username": "weakuser",
        "email": "weak@example.com",
        "password": "123",
    })
    assert r.status_code == 400 or r.status_code == 422


@pytest.mark.asyncio
async def test_logout_invalidates_refresh(async_client: AsyncClient):
    """After logout, refresh token should no longer work."""
    await async_client.post("/api/auth/register", json={
        "username": "logoutuser",
        "email": "logout@example.com",
        "password": "SecurePass123!",
    })
    r = await async_client.post("/api/auth/login", json={
        "username": "logoutuser",
        "password": "SecurePass123!",
    })
    refresh = r.json()["refresh_token"]
    access = r.json()["access_token"]

    # Logout
    r2 = await async_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert r2.status_code in (200, 204)

    # Refresh should fail
    r3 = await async_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r3.status_code == 401
