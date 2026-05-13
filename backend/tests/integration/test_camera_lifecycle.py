"""
Integration tests for camera CRUD, recording control, and stream URLs.
Uses mocked FFmpeg so no real video processes are spawned.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_camera(async_client: AsyncClient, auth_headers: dict):
    """Admin can create a camera."""
    payload = {
        "name": "Cam Create Test",
        "main_stream_url": "rtsp://192.168.1.100:554/stream1",
        "sub_stream_url": "rtsp://192.168.1.100:554/stream2",
        "location": "Building A",
        "recording_mode": "continuous",
        "recording_fps": 25,
    }
    r = await async_client.post("/api/cameras", json=payload, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["name"] == "Cam Create Test"
    assert data["location"] == "Building A"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_cameras(async_client: AsyncClient, auth_headers: dict, test_camera: dict):
    """Camera list includes the test camera."""
    r = await async_client.get("/api/cameras", headers=auth_headers)
    assert r.status_code == 200
    cameras = r.json()
    ids = [c["id"] for c in cameras]
    assert test_camera["id"] in ids


@pytest.mark.asyncio
async def test_get_camera_detail(async_client: AsyncClient, auth_headers: dict, test_camera: dict):
    """Retrieve single camera by ID."""
    r = await async_client.get(f"/api/cameras/{test_camera['id']}", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == test_camera["id"]
    assert data["name"] == test_camera["name"]


@pytest.mark.asyncio
async def test_update_camera(async_client: AsyncClient, auth_headers: dict, test_camera: dict):
    """Update camera fields."""
    r = await async_client.put(
        f"/api/cameras/{test_camera['id']}",
        json={"name": "Updated Name", "location": "New Location"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Updated Name"
    assert data["location"] == "New Location"


@pytest.mark.asyncio
async def test_delete_camera(async_client: AsyncClient, auth_headers: dict, test_camera: dict):
    """Delete camera and verify it's gone."""
    r = await async_client.delete(f"/api/cameras/{test_camera['id']}", headers=auth_headers)
    assert r.status_code in (200, 204)

    r2 = await async_client.get(f"/api/cameras/{test_camera['id']}", headers=auth_headers)
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_recording_start_stop(async_client: AsyncClient, auth_headers: dict, test_camera: dict):
    """Recording toggle endpoints work (FFmpeg is mocked)."""
    # Start
    r1 = await async_client.post(
        f"/api/cameras/{test_camera['id']}/start-recording",
        headers=auth_headers,
    )
    assert r1.status_code == 200, r1.text

    # Stop
    r2 = await async_client.post(
        f"/api/cameras/{test_camera['id']}/stop-recording",
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text


@pytest.mark.asyncio
async def test_camera_groups_crud(async_client: AsyncClient, auth_headers: dict, test_camera: dict):
    """Create, update, assign camera to group, then delete."""
    # Create group
    r1 = await async_client.post("/api/cameras/groups", json={
        "name": "Test Group",
        "description": "For integration tests",
    }, headers=auth_headers)
    assert r1.status_code in (200, 201)
    group = r1.json()

    # Assign camera to group
    r2 = await async_client.put(
        f"/api/cameras/groups/{group['id']}",
        json={"name": "Test Group Updated", "camera_ids": [test_camera["id"]]},
        headers=auth_headers,
    )
    assert r2.status_code == 200

    # Delete group
    r3 = await async_client.delete(f"/api/cameras/groups/{group['id']}", headers=auth_headers)
    assert r3.status_code in (200, 204)


@pytest.mark.asyncio
async def test_unauthorized_camera_access(async_client: AsyncClient):
    """No auth header should reject camera endpoints."""
    r = await async_client.get("/api/cameras")
    assert r.status_code == 401 or r.status_code == 403
