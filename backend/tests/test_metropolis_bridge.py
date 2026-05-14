"""Unit tests for metropolis_bridge translation layer.

Translation is the hot path of the bridge and the place schema drift
hurts most. These tests pin the contract between Metropolis schema and
NVR /api/events/ingest body.
"""
from app.services.metropolis_bridge import (
    metropolis_to_ingest_event,
    _dedup_key,
    _parse_ts,
)


# ── Dedup key stability ────────────────────────────────────────────────


def test_dedup_key_same_inputs_same_hash():
    """Critical: same logical detection → same dedup_key across retries."""
    payload = {
        "sensorId": "cam_1",
        "type": "Person",
        "trackingId": "t-42",
        "timestamp": "2026-05-13T10:00:00Z",
    }
    assert _dedup_key(payload) == _dedup_key(payload)


def test_dedup_key_differs_by_camera():
    base = {
        "sensorId": "cam_1",
        "type": "Person",
        "trackingId": "t-1",
        "timestamp": "2026-05-13T10:00:00Z",
    }
    other = {**base, "sensorId": "cam_2"}
    assert _dedup_key(base) != _dedup_key(other)


def test_dedup_key_accepts_alt_field_names():
    """Bridge tolerates Metropolis canonical AND NVR alias keys."""
    canonical = {"sensorId": "x", "type": "Person", "trackingId": "1", "timestamp": "t"}
    aliased = {"camera_id": "x", "detection_type": "Person", "track_id": "1", "triggered_at": "t"}
    assert _dedup_key(canonical) == _dedup_key(aliased)


# ── Timestamp parsing ──────────────────────────────────────────────────


def test_parse_ts_unix_ms():
    ts = _parse_ts(1715000000000)  # 2024-05-06 something
    assert ts.year >= 2024


def test_parse_ts_unix_seconds():
    ts = _parse_ts(1715000000)
    assert ts.year >= 2024


def test_parse_ts_iso8601():
    ts = _parse_ts("2026-05-13T10:00:00Z")
    assert ts.year == 2026
    assert ts.month == 5


def test_parse_ts_none_returns_now():
    from datetime import datetime
    before = datetime.utcnow()
    ts = _parse_ts(None)
    assert ts >= before


# ── Translation ────────────────────────────────────────────────────────


def test_translate_minimal_face_match():
    payload = {
        "sensorId": "cam_lobby",
        "timestamp": "2026-05-13T10:00:00Z",
        "type": "FaceMatch",
        "analyticsModule": "frs",
        "confidence": 0.92,
        "personId": "p-123",
        "object": {"id": "track-7", "bbox": [10, 20, 50, 80]},
    }
    out = metropolis_to_ingest_event(payload)
    assert out["camera_id"] == "cam_lobby"
    assert out["event_type"] == "facematch"
    assert out["detection_type"] == "FaceMatch"
    assert out["source_service"] == "metropolis-frs"
    assert out["confidence"] == 0.92
    assert out["person_id"] == "p-123"
    assert out["track_id"] == "track-7"
    assert out["bbox"] == [10, 20, 50, 80]
    assert "dedup_key" in out and len(out["dedup_key"]) == 40  # sha1 hex


def test_translate_people_counting():
    payload = {
        "sensorId": "cam_entry",
        "timestamp": 1715000000000,
        "type": "PersonCount",
        "analyticsModule": "people_counting",
        "attributes": {"zone": "entry", "count": 12},
    }
    out = metropolis_to_ingest_event(payload)
    assert out["source_service"] == "metropolis-people_counting"
    assert out["attributes"]["count"] == 12


def test_translate_bbox_dict_form():
    payload = {
        "sensorId": "cam_x",
        "type": "Person",
        "object": {"bbox": {"x": 1, "y": 2, "w": 3, "h": 4}},
        "timestamp": "2026-01-01T00:00:00Z",
    }
    out = metropolis_to_ingest_event(payload)
    assert out["bbox"] == [1, 2, 3, 4]


def test_translate_track_id_int_coerced_to_str():
    payload = {
        "sensorId": "cam_x",
        "type": "Person",
        "object": {"id": 42},
        "timestamp": "2026-01-01T00:00:00Z",
    }
    out = metropolis_to_ingest_event(payload)
    assert out["track_id"] == "42"


def test_translate_no_scenario_falls_back_to_metropolis_source():
    payload = {
        "sensorId": "cam_x",
        "type": "Person",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    out = metropolis_to_ingest_event(payload)
    assert out["source_service"] == "metropolis"
