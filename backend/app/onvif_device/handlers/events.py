# =============================================================================
# ONVIF Event Service handler
# Covers: GetEventProperties, CreatePullPointSubscription, PullMessages,
#         Renew, Unsubscribe, Subscribe (WS-BaseNotification push),
#         GetServiceCapabilities
#
# Module-level state:
#   subscription_queues    — PullPoint per-subscription asyncio.Queue
#   subscription_expires   — PullPoint expiry datetimes
#   push_subscriptions     — BaseNotification push subscriber registry
#   _push_event_queue      — internal queue for the push_delivery_worker
# =============================================================================

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ._common import (
    NS_TEV, NS_WSNT, NS_WSA, NS_TT,
    _qn, _add_text, _base_xaddr, _soap_envelope, _body,
    _extract_subscription_token, _parse_iso_duration,
)

logger = logging.getLogger(__name__)

# ── PullPoint subscription state ─────────────────────────────────────────────
subscription_queues: Dict[str, asyncio.Queue] = {}
subscription_expires: Dict[str, datetime] = {}
_QUEUE_MAX_SIZE = 200
_SUBSCRIPTION_TTL_SECONDS = 300

# ── BaseNotification push subscription state ─────────────────────────────────
push_subscriptions: Dict[str, Dict[str, Any]] = {}

# ── Push delivery queue ───────────────────────────────────────────────────────
_push_event_queue: asyncio.Queue = asyncio.Queue(maxsize=500)


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession,
                   soap_fault_cls=None, **ctx):
    _Fault = soap_fault_cls

    NS_WSTOP = "http://docs.oasis-open.org/wsn/t-1"
    NS_TOPICS = "http://www.onvif.org/ver10/topics"

    if "GetEventProperties" in action:
        resp = etree.SubElement(body, _qn(NS_TEV, "GetEventPropertiesResponse"))
        _add_text(resp, NS_TEV, "TopicNamespaceLocation",
                  "http://www.onvif.org/onvif/ver10/topics/topicns.xml")
        _add_text(resp, NS_TEV, "FixedTopicSet", "true")
        topic_set = etree.SubElement(resp, _qn(NS_TEV, "TopicSet"))
        topic_set.set(f"{{{NS_TOPICS}}}TopicNamespace", "http://www.onvif.org/ver10/topics")
        vs_el = etree.SubElement(topic_set, _qn(NS_TOPICS, "VideoSource"))
        motion = etree.SubElement(vs_el, _qn(NS_TOPICS, "MotionAlarm"))
        motion.set(_qn(NS_WSTOP, "topic"), "true")
        dev_el = etree.SubElement(topic_set, _qn(NS_TOPICS, "Device"))
        trigger = etree.SubElement(dev_el, _qn(NS_TOPICS, "Trigger"))
        di = etree.SubElement(trigger, _qn(NS_TOPICS, "DigitalInput"))
        di.set(_qn(NS_WSTOP, "topic"), "true")
        _add_text(resp, NS_TEV, "TopicExpressionDialect",
                  "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet")
        _add_text(resp, NS_TEV, "MessageContentFilterDialect",
                  "http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter")
        _add_text(resp, NS_TEV, "MessageContentSchemaLocation",
                  "http://www.onvif.org/ver10/schema/onvif.xsd")

    elif "CreatePullPointSubscription" in action:
        sub_token = uuid.uuid4().hex
        subscription_queues[sub_token] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=_SUBSCRIPTION_TTL_SECONDS)
        subscription_expires[sub_token] = expires_at
        resp = etree.SubElement(body, _qn(NS_TEV, "CreatePullPointSubscriptionResponse"))
        ref = etree.SubElement(resp, _qn(NS_WSNT, "SubscriptionReference"))
        addr = etree.SubElement(ref, _qn(NS_WSA, "Address"))
        addr.text = f"{_base_xaddr(request)}/onvif/event_service"
        ref_params = etree.SubElement(ref, _qn(NS_WSA, "ReferenceParameters"))
        token_el = etree.SubElement(ref_params, _qn(NS_TEV, "SubscriptionId"))
        token_el.text = sub_token
        _add_text(resp, NS_WSNT, "CurrentTime", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        _add_text(resp, NS_WSNT, "TerminationTime", expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
        logger.debug(f"ONVIF CreatePullPointSubscription: token={sub_token}")

    elif "PullMessages" in action:
        req_bytes = await request.body()
        sub_token = _extract_subscription_token(req_bytes)
        if not sub_token or sub_token not in subscription_queues:
            sub_token = next(iter(subscription_queues), None)

        timeout_str = _extract_text_field(req_bytes, "Timeout") or "PT5S"
        try:
            if "PT" in timeout_str and "S" in timeout_str:
                pull_timeout = float(timeout_str.replace("PT", "").replace("S", ""))
            else:
                pull_timeout = 5.0
        except Exception:
            pull_timeout = 5.0
        pull_timeout = min(pull_timeout, 30.0)

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=_SUBSCRIPTION_TTL_SECONDS)
        if sub_token and sub_token in subscription_expires:
            expires_at = subscription_expires[sub_token]

        resp = etree.SubElement(body, _qn(NS_TEV, "PullMessagesResponse"))
        _add_text(resp, NS_TEV, "CurrentTime", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        _add_text(resp, NS_TEV, "TerminationTime", expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"))

        msg_limit_str = _extract_text_field(req_bytes, "MessageLimit") or "50"
        try:
            msg_limit = int(msg_limit_str)
        except Exception:
            msg_limit = 50

        events: list = []
        q = subscription_queues.get(sub_token) if sub_token else None
        if q is not None:
            try:
                first = await asyncio.wait_for(q.get(), timeout=pull_timeout)
                events.append(first)
            except asyncio.TimeoutError:
                pass
            while len(events) < msg_limit:
                try:
                    events.append(q.get_nowait())
                except asyncio.QueueEmpty:
                    break

        for evt in events:
            _build_notification_message(resp, evt)

    elif "Renew" in action:
        req_bytes = await request.body()
        sub_token = _extract_subscription_token(req_bytes)
        now = datetime.now(timezone.utc)
        new_expires = now + timedelta(seconds=_SUBSCRIPTION_TTL_SECONDS)
        if sub_token and sub_token in subscription_expires:
            subscription_expires[sub_token] = new_expires
        elif sub_token and sub_token in push_subscriptions:
            term_time_str = _extract_text_field(req_bytes, "TerminationTime") or f"PT{_SUBSCRIPTION_TTL_SECONDS}S"
            ttl_secs = _parse_iso_duration(term_time_str, default=_SUBSCRIPTION_TTL_SECONDS)
            ttl_secs = max(60, min(3600, ttl_secs))
            new_expires = now + timedelta(seconds=ttl_secs)
            push_subscriptions[sub_token]["expires_at"] = new_expires
        resp = etree.SubElement(body, _qn(NS_TEV, "RenewResponse"))
        _add_text(resp, NS_WSNT, "TerminationTime", new_expires.strftime("%Y-%m-%dT%H:%M:%SZ"))
        _add_text(resp, NS_WSNT, "CurrentTime", now.strftime("%Y-%m-%dT%H:%M:%SZ"))

    elif "Unsubscribe" in action:
        req_bytes = await request.body()
        sub_token = _extract_subscription_token(req_bytes)
        if sub_token:
            subscription_queues.pop(sub_token, None)
            subscription_expires.pop(sub_token, None)
            push_subscriptions.pop(sub_token, None)
            logger.debug(f"ONVIF Unsubscribe: removed token={sub_token}")
        etree.SubElement(body, _qn(NS_TEV, "UnsubscribeResponse"))

    elif "Subscribe" in action and "CreatePullPointSubscription" not in action and "Unsubscribe" not in action:
        req_bytes = await request.body()
        consumer_url = _extract_consumer_reference(req_bytes)
        filter_topics = _extract_topic_filter(req_bytes)
        term_time_str = _extract_text_field(req_bytes, "InitialTerminationTime") or "PT5M"
        ttl_secs = _parse_iso_duration(term_time_str, default=300)
        ttl_secs = max(60, min(3600, ttl_secs))

        if not consumer_url:
            if _Fault:
                raise _Fault("ter:InvalidArgVal", "ConsumerReference Address missing or empty")
            return

        push_token = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        push_subscriptions[push_token] = {
            "consumer_url": consumer_url,
            "filter_topics": filter_topics,
            "expires_at": now + timedelta(seconds=ttl_secs),
            "fail_count": 0,
            "created_at": now,
        }
        logger.debug(f"ONVIF Subscribe (push): token={push_token} consumer={consumer_url}")

        resp = etree.SubElement(body, _qn(NS_WSNT, "SubscribeResponse"))
        ref = etree.SubElement(resp, _qn(NS_WSNT, "SubscriptionReference"))
        addr_el = etree.SubElement(ref, _qn(NS_WSA, "Address"))
        addr_el.text = f"{_base_xaddr(request)}/onvif/event_service"
        ref_params = etree.SubElement(ref, _qn(NS_WSA, "ReferenceParameters"))
        token_el = etree.SubElement(ref_params, _qn(NS_TEV, "SubscriptionId"))
        token_el.text = push_token
        _add_text(resp, NS_WSNT, "CurrentTime", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        _add_text(resp, NS_WSNT, "TerminationTime",
                  (now + timedelta(seconds=ttl_secs)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    elif "GetServiceCapabilities" in action:
        resp = etree.SubElement(body, _qn(NS_TEV, "GetServiceCapabilitiesResponse"))
        caps = etree.SubElement(resp, _qn(NS_TEV, "Capabilities"))
        caps.set("WSSubscriptionPolicySupport", "true")
        caps.set("WSPullPointSupport", "true")
        caps.set("WSPausableSubscriptionManagerInterfaceSupport", "false")
        caps.set("MaxNotificationProducers", "1")
        caps.set("MaxPullPoints", "10")
        caps.set("PersistentNotificationStorage", "false")

    else:
        tag = action.split("}")[-1] if "}" in action else action
        if tag:
            etree.SubElement(body, _qn(NS_TEV, tag + "Response"))


# ── Notification message builder ─────────────────────────────────────────────

def _build_notification_message(parent: etree.Element, evt: dict):
    msg_el = etree.SubElement(parent, _qn(NS_WSNT, "NotificationMessage"))
    topic_el = etree.SubElement(msg_el, _qn(NS_WSNT, "Topic"))
    topic_el.set("Dialect", "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet")
    topic_el.text = evt.get("topic", "tns1:VideoSource/MotionAlarm")
    prod_ref = etree.SubElement(msg_el, _qn(NS_WSNT, "ProducerReference"))
    addr_el = etree.SubElement(prod_ref, _qn(NS_WSA, "Address"))
    addr_el.text = evt.get("source", "")
    msg_inner = etree.SubElement(msg_el, _qn(NS_WSNT, "Message"))
    tt_msg = etree.SubElement(msg_inner, _qn(NS_TT, "Message"))
    ts = evt.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    tt_msg.set("UtcTime", ts)
    tt_msg.set("PropertyOperation", "Changed")
    src_el = etree.SubElement(tt_msg, _qn(NS_TT, "Source"))
    si = etree.SubElement(src_el, _qn(NS_TT, "SimpleItem"))
    si.set("Name", "VideoSourceConfigurationToken")
    si.set("Value", evt.get("camera_id", ""))
    data_el = etree.SubElement(tt_msg, _qn(NS_TT, "Data"))
    di = etree.SubElement(data_el, _qn(NS_TT, "SimpleItem"))
    di.set("Name", "IsMotion")
    di.set("Value", str(evt.get("value", "true")).lower())
    for k, v in evt.get("metadata", {}).items():
        if k not in ("onvif_topic", "source"):
            extra = etree.SubElement(data_el, _qn(NS_TT, "SimpleItem"))
            extra.set("Name", str(k))
            extra.set("Value", str(v))


# ── Push delivery helpers ─────────────────────────────────────────────────────

def _enqueue_push_event(evt: dict):
    try:
        _push_event_queue.put_nowait(evt)
    except Exception:
        pass


def _build_notify_envelope(evt: dict) -> bytes:
    env = _soap_envelope()
    bd = _body(env)
    notify = etree.SubElement(bd, _qn(NS_WSNT, "Notify"))
    msg_el = etree.SubElement(notify, _qn(NS_WSNT, "NotificationMessage"))
    topic_el = etree.SubElement(msg_el, _qn(NS_WSNT, "Topic"))
    topic_el.set("Dialect", "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet")
    topic_el.text = evt.get("topic", "tns1:VideoSource/MotionAlarm")
    prod_ref = etree.SubElement(msg_el, _qn(NS_WSNT, "ProducerReference"))
    addr_el = etree.SubElement(prod_ref, _qn(NS_WSA, "Address"))
    addr_el.text = evt.get("source", "")
    msg_inner = etree.SubElement(msg_el, _qn(NS_WSNT, "Message"))
    tt_msg = etree.SubElement(msg_inner, _qn(NS_TT, "Message"))
    ts = evt.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    tt_msg.set("UtcTime", ts)
    tt_msg.set("PropertyOperation", "Changed")
    src_el = etree.SubElement(tt_msg, _qn(NS_TT, "Source"))
    si = etree.SubElement(src_el, _qn(NS_TT, "SimpleItem"))
    si.set("Name", "VideoSourceConfigurationToken")
    si.set("Value", evt.get("camera_id", ""))
    data_el = etree.SubElement(tt_msg, _qn(NS_TT, "Data"))
    di = etree.SubElement(data_el, _qn(NS_TT, "SimpleItem"))
    di.set("Name", "IsMotion")
    di.set("Value", str(evt.get("value", "true")).lower())
    for k, v in evt.get("metadata", {}).items():
        if k not in ("onvif_topic", "source"):
            extra = etree.SubElement(data_el, _qn(NS_TT, "SimpleItem"))
            extra.set("Name", str(k))
            extra.set("Value", str(v))
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8")


async def sweep_expired_subscriptions():
    """Background task: remove expired PullPoint and push subscriptions every 30s."""
    while True:
        try:
            await asyncio.sleep(30)
            now = datetime.now(timezone.utc)
            expired_pull = [
                token for token, exp in list(subscription_expires.items())
                if exp <= now
            ]
            for token in expired_pull:
                subscription_queues.pop(token, None)
                subscription_expires.pop(token, None)
                logger.debug(f"ONVIF: swept expired pull subscription token={token}")
            expired_push = [
                token for token, sub in list(push_subscriptions.items())
                if sub["expires_at"] <= now
            ]
            for token in expired_push:
                push_subscriptions.pop(token, None)
                logger.debug(f"ONVIF: swept expired push subscription token={token}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"sweep_expired_subscriptions error: {e}")


async def push_delivery_worker():
    """Background task: deliver events to BaseNotification push subscribers via HTTP POST."""
    import httpx
    while True:
        try:
            evt = await _push_event_queue.get()
            if not push_subscriptions:
                continue
            now = datetime.now(timezone.utc)
            dead_tokens = []
            for token, sub in list(push_subscriptions.items()):
                if sub["expires_at"] <= now:
                    dead_tokens.append(token)
                    continue
                if sub["filter_topics"]:
                    topic = evt.get("topic", "")
                    if not any(topic.startswith(ft) for ft in sub["filter_topics"]):
                        continue
                notify_xml = _build_notify_envelope(evt)
                consumer_url = sub["consumer_url"]
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.post(
                            consumer_url,
                            content=notify_xml,
                            headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                        )
                    if resp.status_code < 400:
                        sub["fail_count"] = 0
                        logger.debug(f"ONVIF push delivered to {consumer_url} status={resp.status_code}")
                    else:
                        sub["fail_count"] = sub.get("fail_count", 0) + 1
                        logger.warning(f"ONVIF push: consumer {consumer_url} returned {resp.status_code} (fail #{sub['fail_count']})")
                        if sub["fail_count"] >= 3:
                            dead_tokens.append(token)
                except Exception as e:
                    sub["fail_count"] = sub.get("fail_count", 0) + 1
                    logger.warning(f"ONVIF push: delivery to {consumer_url} failed: {e} (fail #{sub['fail_count']})")
                    if sub["fail_count"] >= 3:
                        dead_tokens.append(token)
            for token in dead_tokens:
                push_subscriptions.pop(token, None)
                logger.info(f"ONVIF: removed dead push subscription token={token}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"push_delivery_worker error: {e}")


async def inject_nvr_event(
    camera_id: Optional[str] = None,
    event_type: str = "motion_detected",
    severity: str = "alarm",
    title: str = "",
    metadata: Optional[Dict[str, Any]] = None,
):
    """Push an NVR-internal event into all active ONVIF PullPoint queues."""
    if not subscription_queues:
        return
    topic_map = {
        "motion_detected": "tns1:VideoSource/MotionAlarm",
        "camera_tamper":   "tns1:VideoSource/ImageTooBlurry",
        "video_loss":      "tns1:VideoSource/ConnectionFailed",
        "line_crossing":   "tns1:RuleEngine/LineDetector/Crossed",
        "zone_intrusion":  "tns1:RuleEngine/FieldDetector/ObjectInside",
        "audio_alarm":     "tns1:AudioAnalytics/Audio/DetectedSound",
        "system_error":    "tns1:Device/Trigger/DigitalInput",
    }
    topic = topic_map.get(event_type, "tns1:VideoSource/MotionAlarm")
    evt = {
        "topic": topic,
        "camera_id": camera_id or "",
        "source": f"camera:{camera_id}" if camera_id else "nvr:system",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "value": "true",
        "metadata": metadata or {"nvr_event_type": event_type, "severity": severity},
    }
    for q in list(subscription_queues.values()):
        try:
            q.put_nowait(evt)
        except Exception:
            pass
    _enqueue_push_event(evt)


# ── Private XML helpers local to events ──────────────────────────────────────

def _extract_text_field(xml_bytes: bytes, field: str) -> Optional[str]:
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        el = root.find(".//" + field)
        if el is None:
            el = root.find(".//{*}" + field)
        if el is not None:
            return el.text
    except Exception:
        pass
    return None


def _extract_consumer_reference(xml_bytes: bytes) -> Optional[str]:
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        for tag in ("{%s}ConsumerReference" % NS_WSNT, "ConsumerReference"):
            cr = root.find(".//" + tag)
            if cr is not None:
                for addr_tag in ("{%s}Address" % NS_WSA, "Address"):
                    addr_el = cr.find(".//" + addr_tag)
                    if addr_el is not None and addr_el.text:
                        return addr_el.text.strip()
    except Exception:
        pass
    return None


def _extract_topic_filter(xml_bytes: bytes) -> list:
    topics = []
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        for tag in ("{%s}Filter" % NS_WSNT, "Filter"):
            flt = root.find(".//" + tag)
            if flt is not None:
                for child in flt:
                    if child.text:
                        topics.extend(
                            t.strip().strip('"') for t in child.text.split("|") if t.strip()
                        )
    except Exception:
        pass
    return topics
