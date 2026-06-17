"""ONVIF Profile M/T metadata XML parsing and ingestion.

This module handles camera-generated metadata only. It normalizes XML payloads
from metadata RTSP streams or WS-Notification messages into generic NVR events;
it does not run internal AI inference.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from lxml import etree


def _local_name(node: etree._Element) -> str:
    return etree.QName(node).localname


def _attr(node: etree._Element, name: str) -> Optional[str]:
    for key, value in node.attrib.items():
        if etree.QName(key).localname == name:
            return value
    return None


def _float_attr(node: etree._Element, name: str) -> Optional[float]:
    value = _attr(node, name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_xml(xml_bytes: bytes | str) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8")
    return etree.fromstring((xml_bytes or b"").lstrip(), parser=parser)


def _simple_items(parent: etree._Element) -> Dict[str, Any]:
    items: Dict[str, Any] = {}
    for node in parent.xpath(".//*[local-name()='SimpleItem']"):
        name = _attr(node, "Name")
        if name:
            items[name] = _attr(node, "Value")
    return items


def _bounding_box(node: etree._Element) -> Optional[Dict[str, float]]:
    box = node.xpath(".//*[local-name()='BoundingBox']")
    if not box:
        return None
    box_node = box[0]
    values = {
        "left": _float_attr(box_node, "left"),
        "top": _float_attr(box_node, "top"),
        "right": _float_attr(box_node, "right"),
        "bottom": _float_attr(box_node, "bottom"),
    }
    return values if all(v is not None for v in values.values()) else None


def _classifications(node: etree._Element) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for cls in node.xpath(".//*[local-name()='ClassCandidate']"):
        out.append({
            "type": _attr(cls, "Type"),
            "likelihood": _float_attr(cls, "Likelihood"),
        })
    return out


def _objects(root: etree._Element) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for obj in root.xpath(".//*[local-name()='Object']"):
        item = {
            "object_id": _attr(obj, "ObjectId"),
            "bbox": _bounding_box(obj),
            "classifications": _classifications(obj),
        }
        out.append({k: v for k, v in item.items() if v not in (None, [], {})})
    return out


def _notification_topics(root: etree._Element) -> List[str]:
    topics: List[str] = []
    for topic in root.xpath(".//*[local-name()='NotificationMessage']/*[local-name()='Topic']"):
        value = "".join(topic.itertext()).strip()
        if value:
            topics.append(value)
    return topics


def parse_metadata_xml(xml_bytes: bytes | str) -> List[Dict[str, Any]]:
    """Parse ONVIF metadata XML into generic event payloads."""
    root = _parse_xml(xml_bytes)
    source = _simple_items(root)
    objects = _objects(root)
    topics = _notification_topics(root)

    utc_times = [
        _attr(frame, "UtcTime")
        for frame in root.xpath(".//*[local-name()='Frame']")
        if _attr(frame, "UtcTime")
    ]
    timestamp = utc_times[0] if utc_times else None

    if topics:
        return [
            {
                "event_type": "onvif_metadata",
                "severity": "info",
                "title": "ONVIF metadata event",
                "description": f"ONVIF metadata topic: {topic}",
                "metadata": {
                    "onvif_topic": topic,
                    "onvif": {
                        "source": source,
                        "objects": objects,
                        "timestamp": timestamp,
                    },
                },
            }
            for topic in topics
        ]

    if objects or source or timestamp:
        return [{
            "event_type": "onvif_metadata",
            "severity": "info",
            "title": "ONVIF metadata frame",
            "description": "ONVIF metadata stream frame",
            "metadata": {
                "onvif": {
                    "source": source,
                    "objects": objects,
                    "timestamp": timestamp,
                },
            },
        }]

    return []


async def ingest_metadata_xml(camera_id: str, xml_bytes: bytes | str) -> int:
    """Persist parsed metadata XML as generic NVR events."""
    events = parse_metadata_xml(xml_bytes)
    if not events:
        return 0

    from app.events.linkage_service import linkage_engine

    for event in events:
        await linkage_engine.fire_event(
            camera_id=camera_id,
            event_type=event["event_type"],
            severity=event["severity"],
            title=event["title"],
            description=event.get("description"),
            metadata=event.get("metadata"),
        )
    return len(events)
