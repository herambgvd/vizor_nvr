from datetime import datetime, timezone

import pytest


class _Obj:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeRecordingServiceUnavailable:
    def GetRecordings(self):
        raise RuntimeError("recording inventory unavailable")


class _FakeSearchService:
    def __init__(self):
        self.find_calls = []
        self.result_calls = []

    def FindRecordings(self, request):
        self.find_calls.append(request)
        return _Obj(SearchToken="search-token-1")

    def GetRecordingSearchResults(self, request):
        self.result_calls.append(request)
        return _Obj(
            RecordingResult=[
                _Obj(
                    RecordingToken="recording-token-1",
                    TrackList=_Obj(
                        Track=[
                            _Obj(
                                TrackToken="track-video-1",
                                StartTime="2026-06-14T01:00:00Z",
                                EndTime="2026-06-14T01:05:00Z",
                            )
                        ]
                    ),
                )
            ]
        )


class _FakeProfileGCamera:
    search_service = _FakeSearchService()

    def __init__(self, *_args, **_kwargs):
        pass

    def create_recording_service(self):
        return _FakeRecordingServiceUnavailable()

    def create_search_service(self):
        return self.search_service


@pytest.mark.asyncio
async def test_profile_g_search_uses_search_service_for_find_recordings(monkeypatch):
    from app.cameras import onvif_service as module

    monkeypatch.setattr(module, "_HAS_ONVIF", True)
    monkeypatch.setattr(module, "ONVIFCamera", _FakeProfileGCamera)

    start = datetime(2026, 6, 14, 1, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 14, 1, 10, tzinfo=timezone.utc)
    result = await module.ONVIFService().search_recordings(
        "camera",
        80,
        "admin",
        "admin",
        start,
        end,
    )

    assert result == [
        {
            "recording_token": "recording-token-1",
            "track_token": "track-video-1",
            "start_time": datetime(2026, 6, 14, 1, 0, tzinfo=timezone.utc),
            "end_time": datetime(2026, 6, 14, 1, 5, tzinfo=timezone.utc),
        }
    ]
    assert _FakeProfileGCamera.search_service.find_calls[0]["Scope"]["StartTime"] == (
        "2026-06-14T01:00:00+00:00"
    )
    assert _FakeProfileGCamera.search_service.result_calls[0]["SearchToken"] == "search-token-1"
