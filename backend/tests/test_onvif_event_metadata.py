from app.cameras.onvif_event_service import _extract_metadata, _resolve_topic


class _Obj:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_unknown_analytics_topic_maps_to_generic_profile_m_event():
    mapping = _resolve_topic("tns1:RuleEngine/ObjectDetector/Object")

    assert mapping == ("onvif_metadata", "info", "ONVIF metadata event")


def test_extract_metadata_preserves_profile_m_source_data_and_elements():
    msg = _Obj(
        ProducerReference=_Obj(Address="urn:uuid:camera-1"),
        Message=_Obj(
            Message=_Obj(
                Source=_Obj(
                    SimpleItem=[
                        _Obj(Name="VideoSourceConfigurationToken", Value="vsrc-1"),
                        _Obj(Name="Rule", Value="line-1"),
                    ]
                ),
                Data=_Obj(
                    SimpleItem=[
                        _Obj(Name="State", Value="true"),
                        _Obj(Name="ObjectId", Value="42"),
                        _Obj(Name="Confidence", Value=0.87),
                    ],
                    ElementItem=[
                        _Obj(
                            Name="BoundingBox",
                            Value=_Obj(left=0.1, top=0.2, right=0.5, bottom=0.8),
                        )
                    ],
                ),
            )
        ),
    )

    meta = _extract_metadata(msg)

    assert meta["source"] == "urn:uuid:camera-1"
    assert meta["State"] == "true"
    assert meta["ObjectId"] == "42"
    assert meta["Confidence"] == 0.87
    assert meta["onvif"]["producer_reference"] == "urn:uuid:camera-1"
    assert meta["onvif"]["source"]["Rule"] == "line-1"
    assert meta["onvif"]["data"]["ObjectId"] == "42"
    assert meta["onvif"]["elements"]["BoundingBox"] == {
        "left": 0.1,
        "top": 0.2,
        "right": 0.5,
        "bottom": 0.8,
    }
