import pytest


class _Obj:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeDeviceMgmt:
    def GetCapabilities(self):
        return _Obj()

    def GetServices(self, _request):
        return [
            _Obj(
                Namespace="http://www.onvif.org/ver20/media/wsdl/media2",
                XAddr="http://camera/onvif/media2",
            )
        ]


class _FakeMedia2:
    def GetProfiles(self, _request):
        return [
            _Obj(
                token="profile-main",
                VideoEncoderConfiguration=_Obj(Encoding="H265"),
                MetadataConfiguration=_Obj(token="meta-main"),
            ),
            _Obj(
                token="profile-sub",
                VideoEncoderConfiguration=_Obj(Encoding="H264"),
            ),
        ]

    def GetStreamUri(self, request):
        token = request["ProfileToken"]
        return _Obj(Uri=f"rtsp://camera/{token}")

    def GetAudioEncoderConfigurations(self):
        return [
            _Obj(
                token="audio-main",
                Name="AAC Main",
                Encoding="AAC",
                Bitrate=64,
                SampleRate=48,
                UseCount=1,
            )
        ]

    def GetMetadataConfigurations(self):
        return [
            _Obj(
                token="meta-main",
                Name="Metadata Main",
                Events=_Obj(),
                Analytics=_Obj(),
                UseCount=1,
            )
        ]


class _FakeCamera:
    def __init__(self, *_args, **_kwargs):
        self.devicemgmt = _FakeDeviceMgmt()

    def create_media2_service(self):
        return _FakeMedia2()


class _FakeMedia2WithoutOptionalConfigs(_FakeMedia2):
    def GetAudioEncoderConfigurations(self):
        raise RuntimeError("not supported")

    def GetMetadataConfigurations(self):
        raise RuntimeError("not supported")


class _FakeCameraWithoutOptionalConfigs(_FakeCamera):
    def create_media2_service(self):
        return _FakeMedia2WithoutOptionalConfigs()


@pytest.mark.asyncio
async def test_media2_stream_discovery_includes_audio_and_metadata(monkeypatch):
    from app.cameras import onvif_service as module

    monkeypatch.setattr(module, "_HAS_ONVIF", True)
    monkeypatch.setattr(module, "ONVIFCamera", _FakeCamera)

    result = await module.ONVIFService().get_stream_uris_media2(
        "camera",
        80,
        "user@example.com",
        "p@ss:word",
    )

    assert result["main_stream_url"] == (
        "rtsp://user%40example.com:p%40ss%3Aword@camera/profile-main"
    )
    assert result["sub_stream_url"] == (
        "rtsp://user%40example.com:p%40ss%3Aword@camera/profile-sub"
    )
    assert result["codec"] == "H265"
    assert result["audio_encoder_configurations"] == [
        {
            "token": "audio-main",
            "name": "AAC Main",
            "encoding": "AAC",
            "bitrate": 64,
            "sample_rate": 48,
            "use_count": 1,
        }
    ]
    assert result["metadata_supported"] is True
    assert result["metadata_stream_url"] == (
        "rtsp://user%40example.com:p%40ss%3Aword@camera/profile-main"
    )
    assert result["metadata_profile_token"] == "profile-main"
    assert result["metadata_configurations"][0]["token"] == "meta-main"
    assert result["metadata_configurations"][0]["events_enabled"] is True
    assert result["metadata_configurations"][0]["analytics_enabled"] is True


@pytest.mark.asyncio
async def test_media2_stream_discovery_keeps_defaults_when_optional_queries_fail(monkeypatch):
    from app.cameras import onvif_service as module

    monkeypatch.setattr(module, "_HAS_ONVIF", True)
    monkeypatch.setattr(module, "ONVIFCamera", _FakeCameraWithoutOptionalConfigs)

    result = await module.ONVIFService().get_stream_uris_media2(
        "camera",
        80,
        "admin",
        "admin",
    )

    assert result["main_stream_url"] == "rtsp://admin:admin@camera/profile-main"
    assert result["audio_encoder_configurations"] == []
    assert result["metadata_configurations"] == []
    assert result["metadata_supported"] is True
    assert result["metadata_stream_url"] == "rtsp://admin:admin@camera/profile-main"


@pytest.mark.asyncio
async def test_metadata_stream_discovery_prefers_media2_metadata_profile(monkeypatch):
    from app.cameras import onvif_service as module

    monkeypatch.setattr(module, "_HAS_ONVIF", True)
    monkeypatch.setattr(module, "ONVIFCamera", _FakeCamera)

    result = await module.ONVIFService().get_metadata_stream_uri(
        "camera",
        80,
        "admin",
        "pass word",
    )

    assert result == {
        "supported": True,
        "uri": "rtsp://admin:pass%20word@camera/profile-main",
        "media_version": 2,
        "profile_token": "profile-main",
        "metadata_config_token": "meta-main",
    }
