from app.cameras.onvif_metadata import parse_metadata_xml


def test_parse_metadata_stream_frame_with_object_bbox_and_classification():
    xml = b"""
    <tt:MetadataStream xmlns:tt="http://www.onvif.org/ver10/schema">
      <tt:VideoAnalytics>
        <tt:Frame UtcTime="2026-06-15T10:00:00Z">
          <tt:Object ObjectId="17">
            <tt:Appearance>
              <tt:Shape>
                <tt:BoundingBox left="0.1" top="0.2" right="0.5" bottom="0.8"/>
              </tt:Shape>
              <tt:Class>
                <tt:ClassCandidate Type="Person" Likelihood="0.91"/>
              </tt:Class>
            </tt:Appearance>
          </tt:Object>
        </tt:Frame>
      </tt:VideoAnalytics>
    </tt:MetadataStream>
    """

    events = parse_metadata_xml(xml)

    assert len(events) == 1
    assert events[0]["event_type"] == "onvif_metadata"
    metadata = events[0]["metadata"]["onvif"]
    assert metadata["timestamp"] == "2026-06-15T10:00:00Z"
    assert metadata["objects"] == [
        {
            "object_id": "17",
            "bbox": {"left": 0.1, "top": 0.2, "right": 0.5, "bottom": 0.8},
            "classifications": [{"type": "Person", "likelihood": 0.91}],
        }
    ]


def test_parse_notification_message_topic():
    xml = b"""
    <wsnt:Notify xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2">
      <wsnt:NotificationMessage>
        <wsnt:Topic Dialect="x">tns1:RuleEngine/LineDetector/Crossed</wsnt:Topic>
        <wsnt:Message>
          <tt:Message xmlns:tt="http://www.onvif.org/ver10/schema">
            <tt:Source>
              <tt:SimpleItem Name="Rule" Value="line-1"/>
            </tt:Source>
          </tt:Message>
        </wsnt:Message>
      </wsnt:NotificationMessage>
    </wsnt:Notify>
    """

    events = parse_metadata_xml(xml)

    assert len(events) == 1
    assert events[0]["description"] == (
        "ONVIF metadata topic: tns1:RuleEngine/LineDetector/Crossed"
    )
    assert events[0]["metadata"]["onvif_topic"] == "tns1:RuleEngine/LineDetector/Crossed"
    assert events[0]["metadata"]["onvif"]["source"]["Rule"] == "line-1"
