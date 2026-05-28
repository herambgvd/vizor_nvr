#!/usr/bin/env python3
"""
ONVIF Profile S/T/G Conformance Smoke-Test for GVD NVR
=======================================================
Calls each Profile S mandatory operation (plus selected Profile T and G ops)
against the running NVR ONVIF device service and prints a pass/fail table.

Usage (inside Docker):
    docker compose exec backend python scripts/onvif_conformance_check.py

Or with custom host/credentials:
    ONVIF_HOST=192.168.1.100:8000 ONVIF_USER=admin ONVIF_PASS=Admin@12345 \\
        python scripts/onvif_conformance_check.py

Exit code: 0 if all mandatory ops pass, 1 otherwise.
"""

import os
import sys
import uuid
import base64
import hashlib
import datetime
import textwrap
from dataclasses import dataclass, field
from typing import List, Optional

import requests
from lxml import etree

# ── Configuration ────────────────────────────────────────────────────────────
HOST     = os.getenv("ONVIF_HOST", "localhost:8000")
# Default matches the device-server's own default (admin/admin from
# ONVIF_DEVICE_USERNAME / ONVIF_DEVICE_PASSWORD in .env). Override via
# ONVIF_USER / ONVIF_PASS env vars when the operator has rotated them.
USERNAME = os.getenv("ONVIF_USER", os.getenv("ONVIF_DEVICE_USERNAME", "admin"))
PASSWORD = os.getenv("ONVIF_PASS", os.getenv("ONVIF_DEVICE_PASSWORD", "admin"))
SCHEME   = os.getenv("ONVIF_SCHEME", "http")

DEVICE_SERVICE  = f"{SCHEME}://{HOST}/onvif/device_service"
MEDIA_SERVICE   = f"{SCHEME}://{HOST}/onvif/media_service"
MEDIA2_SERVICE  = f"{SCHEME}://{HOST}/onvif/media2_service"
PTZ_SERVICE     = f"{SCHEME}://{HOST}/onvif/ptz_service"
EVENT_SERVICE   = f"{SCHEME}://{HOST}/onvif/event_service"
RECORD_SERVICE  = f"{SCHEME}://{HOST}/onvif/recording_service"
SEARCH_SERVICE  = f"{SCHEME}://{HOST}/onvif/search_service"
REPLAY_SERVICE  = f"{SCHEME}://{HOST}/onvif/replay_service"

TIMEOUT = 10  # seconds

# ── Namespace constants ───────────────────────────────────────────────────────
NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
NS_WSU  = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
NS_TDS  = "http://www.onvif.org/ver10/device/wsdl"
NS_TRT  = "http://www.onvif.org/ver10/media/wsdl"
NS_TR2  = "http://www.onvif.org/ver20/media/wsdl"
NS_TPTZ = "http://www.onvif.org/ver20/ptz/wsdl"
NS_TEV  = "http://www.onvif.org/ver10/events/wsdl"
NS_TRC  = "http://www.onvif.org/ver10/recording/wsdl"
NS_TSE  = "http://www.onvif.org/ver10/search/wsdl"
NS_TRP  = "http://www.onvif.org/ver10/replay/wsdl"
NS_TT   = "http://www.onvif.org/ver10/schema"


# ── SOAP helpers ──────────────────────────────────────────────────────────────

def _wsse_header() -> str:
    """Build WS-UsernameToken PasswordDigest header."""
    nonce_raw = os.urandom(20)
    nonce_b64  = base64.b64encode(nonce_raw).decode()
    created    = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest_raw = base64.b64encode(
        hashlib.sha1(nonce_raw + created.encode() + PASSWORD.encode()).digest()
    ).decode()
    return f"""<wsse:Security xmlns:wsse="{NS_WSSE}" xmlns:wsu="{NS_WSU}">
  <wsse:UsernameToken>
    <wsse:Username>{USERNAME}</wsse:Username>
    <wsse:Password Type="{NS_WSSE}#PasswordDigest">{digest_raw}</wsse:Password>
    <wsse:Nonce EncodingType="{NS_WSSE}#Base64Binary">{nonce_b64}</wsse:Nonce>
    <wsu:Created>{created}</wsu:Created>
  </wsse:UsernameToken>
</wsse:Security>"""


def _envelope(ns: str, action: str, body_inner: str = "") -> str:
    header = _wsse_header()
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <s:Envelope xmlns:s="{NS_SOAP}"
                    xmlns:tds="{NS_TDS}"
                    xmlns:trt="{NS_TRT}"
                    xmlns:tr2="{NS_TR2}"
                    xmlns:tptz="{NS_TPTZ}"
                    xmlns:tev="{NS_TEV}"
                    xmlns:trc="{NS_TRC}"
                    xmlns:tse="{NS_TSE}"
                    xmlns:trp="{NS_TRP}"
                    xmlns:tt="{NS_TT}">
          <s:Header>{header}</s:Header>
          <s:Body>{body_inner}</s:Body>
        </s:Envelope>""")


def _call(url: str, action: str, body_inner: str = "") -> Optional[etree.Element]:
    """Send SOAP request, return parsed root element or None on error."""
    ns = ""
    payload = _envelope(ns, action, body_inner)
    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "SOAPAction": f'"{action}"',
    }
    try:
        r = requests.post(url, data=payload.encode(), headers=headers, timeout=TIMEOUT)
        root = etree.fromstring(r.content)
        return root
    except Exception as e:
        return None


def _find(root: etree.Element, *tags) -> Optional[str]:
    """Find first matching tag text."""
    for tag in tags:
        el = root.find(f".//{{{NS_SOAP}}}Fault")
        if el is not None:
            return None  # caller detects fault
        el = root.find(f".//{tag}")
        if el is not None:
            return el.text
    return None


def _has_fault(root: Optional[etree.Element]) -> bool:
    if root is None:
        return True
    return root.find(f".//{{{NS_SOAP}}}Fault") is not None


def _has_response(root: Optional[etree.Element], response_tag: str) -> bool:
    """Check that a response element (or valid empty response) exists."""
    if root is None:
        return False
    if _has_fault(root):
        return False
    # Accept any element whose local name ends with the tag
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local == response_tag:
            return True
    return False


# ── Result tracking ──────────────────────────────────────────────────────────

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

@dataclass
class Result:
    profile:   str
    service:   str
    operation: str
    mandatory: bool
    status:    str = FAIL
    note:      str = ""

results: List[Result] = []


def check(profile: str, service: str, operation: str, mandatory: bool,
          url: str, action_ns: str, action_name: str,
          body_inner: str = "", response_tag: Optional[str] = None,
          custom_check=None) -> Result:
    action = f"{action_ns}/{action_name}"
    tag = response_tag or (action_name + "Response")
    root = _call(url, action, body_inner)
    if custom_check:
        ok, note = custom_check(root)
    else:
        ok = _has_response(root, tag)
        note = ""
        if root is not None and _has_fault(root):
            fault_el = root.find(f".//{{{NS_SOAP}}}Fault")
            if fault_el is not None:
                note = etree.tostring(fault_el, encoding="unicode")[:80]
    r = Result(profile=profile, service=service, operation=operation,
               mandatory=mandatory, status=PASS if ok else FAIL, note=note)
    results.append(r)
    return r


# ── Profile token helper (from GetProfiles) ───────────────────────────────────

_profile_token: Optional[str] = None

def _get_profile_token() -> str:
    global _profile_token
    if _profile_token:
        return _profile_token
    root = _call(MEDIA_SERVICE,
                 f"{NS_TRT}/GetProfiles",
                 "<trt:GetProfiles/>")
    if root is not None:
        for el in root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if local == "Profiles":
                tok = el.get("token") or el.get(f"{{{NS_TT}}}token")
                if tok:
                    _profile_token = tok
                    return tok
    _profile_token = "profile_1"
    return _profile_token


# ── Tests ────────────────────────────────────────────────────────────────────

def run_all():
    # ── Profile S — Device Service ──────────────────────────────────────────
    check("S", "Device", "GetSystemDateAndTime", True,
          DEVICE_SERVICE, NS_TDS,
          "GetSystemDateAndTime",
          "<tds:GetSystemDateAndTime/>",
          "GetSystemDateAndTimeResponse")

    check("S", "Device", "GetDeviceInformation", True,
          DEVICE_SERVICE, NS_TDS,
          "GetDeviceInformation",
          "<tds:GetDeviceInformation/>",
          "GetDeviceInformationResponse")

    check("S", "Device", "GetCapabilities", True,
          DEVICE_SERVICE, NS_TDS,
          "GetCapabilities",
          "<tds:GetCapabilities/>",
          "GetCapabilitiesResponse")

    check("S", "Device", "GetServices", True,
          DEVICE_SERVICE, NS_TDS,
          "GetServices",
          "<tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices>",
          "GetServicesResponse")

    check("S", "Device", "GetServiceCapabilities", True,
          DEVICE_SERVICE, NS_TDS,
          "GetServiceCapabilities",
          "<tds:GetServiceCapabilities/>",
          "GetServiceCapabilitiesResponse")

    check("S", "Device", "GetScopes", True,
          DEVICE_SERVICE, NS_TDS,
          "GetScopes",
          "<tds:GetScopes/>",
          "GetScopesResponse",
          custom_check=lambda root: (
              _has_response(root, "GetScopesResponse") and
              b"Profile/Streaming" in (etree.tostring(root) if root is not None else b""),
              "Profile/Streaming scope present" if root is not None and b"Profile/Streaming" in etree.tostring(root) else "Missing Profile/Streaming scope"
          ))

    check("S", "Device", "GetNetworkInterfaces", True,
          DEVICE_SERVICE, NS_TDS,
          "GetNetworkInterfaces",
          "<tds:GetNetworkInterfaces/>",
          "GetNetworkInterfacesResponse")

    check("S", "Device", "GetHostname", False,
          DEVICE_SERVICE, NS_TDS,
          "GetHostname",
          "<tds:GetHostname/>",
          "GetHostnameResponse")

    check("S", "Device", "GetUsers", False,
          DEVICE_SERVICE, NS_TDS,
          "GetUsers",
          "<tds:GetUsers/>",
          "GetUsersResponse")

    check("S", "Device", "SystemReboot", False,
          DEVICE_SERVICE, NS_TDS,
          "SystemReboot",
          "<tds:SystemReboot/>",
          "SystemRebootResponse")

    # ── Profile S — Media Service ────────────────────────────────────────────
    check("S", "Media", "GetProfiles", True,
          MEDIA_SERVICE, NS_TRT,
          "GetProfiles",
          "<trt:GetProfiles/>",
          "GetProfilesResponse")

    profile_token = _get_profile_token()

    check("S", "Media", "GetStreamUri", True,
          MEDIA_SERVICE, NS_TRT,
          "GetStreamUri",
          f"""<trt:GetStreamUri>
                <trt:StreamSetup>
                  <tt:Stream>RTP-Unicast</tt:Stream>
                  <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
                </trt:StreamSetup>
                <trt:ProfileToken>{profile_token}</trt:ProfileToken>
              </trt:GetStreamUri>""",
          "GetStreamUriResponse",
          custom_check=lambda root: (
              _has_response(root, "GetStreamUriResponse"),
              "Response present (URI empty when no cameras registered)" if _has_response(root, "GetStreamUriResponse") else "No response"
          ))

    check("S", "Media", "GetSnapshotUri", True,
          MEDIA_SERVICE, NS_TRT,
          "GetSnapshotUri",
          f"<trt:GetSnapshotUri><trt:ProfileToken>{profile_token}</trt:ProfileToken></trt:GetSnapshotUri>",
          "GetSnapshotUriResponse")

    check("S", "Media", "GetVideoSources", True,
          MEDIA_SERVICE, NS_TRT,
          "GetVideoSources",
          "<trt:GetVideoSources/>",
          "GetVideoSourcesResponse")

    check("S", "Media", "GetVideoSourceConfigurations", True,
          MEDIA_SERVICE, NS_TRT,
          "GetVideoSourceConfigurations",
          "<trt:GetVideoSourceConfigurations/>",
          "GetVideoSourceConfigurationsResponse")

    check("S", "Media", "GetVideoEncoderConfigurations", True,
          MEDIA_SERVICE, NS_TRT,
          "GetVideoEncoderConfigurations",
          "<trt:GetVideoEncoderConfigurations/>",
          "GetVideoEncoderConfigurationsResponse")

    check("S", "Media", "GetAudioSources", False,
          MEDIA_SERVICE, NS_TRT,
          "GetAudioSources",
          "<trt:GetAudioSources/>",
          "GetAudioSourcesResponse")

    check("S", "Media", "GetAudioEncoderConfigurations", False,
          MEDIA_SERVICE, NS_TRT,
          "GetAudioEncoderConfigurations",
          "<trt:GetAudioEncoderConfigurations/>",
          "GetAudioEncoderConfigurationsResponse")

    # ── Profile S — PTZ Service ──────────────────────────────────────────────
    check("S", "PTZ", "GetConfigurations", True,
          PTZ_SERVICE, NS_TPTZ,
          "GetConfigurations",
          "<tptz:GetConfigurations/>",
          "GetConfigurationsResponse")

    check("S", "PTZ", "GetPresets", True,
          PTZ_SERVICE, NS_TPTZ,
          "GetPresets",
          f"<tptz:GetPresets><tptz:ProfileToken>{profile_token}</tptz:ProfileToken></tptz:GetPresets>",
          "GetPresetsResponse")

    check("S", "PTZ", "GotoPreset", True,
          PTZ_SERVICE, NS_TPTZ,
          "GotoPreset",
          f"""<tptz:GotoPreset>
                <tptz:ProfileToken>{profile_token}</tptz:ProfileToken>
                <tptz:PresetToken>1</tptz:PresetToken>
              </tptz:GotoPreset>""",
          "GotoPresetResponse")

    check("S", "PTZ", "ContinuousMove", False,
          PTZ_SERVICE, NS_TPTZ,
          "ContinuousMove",
          f"""<tptz:ContinuousMove>
                <tptz:ProfileToken>{profile_token}</tptz:ProfileToken>
                <tptz:Velocity>
                  <tt:PanTilt x="0" y="0"/>
                  <tt:Zoom x="0"/>
                </tptz:Velocity>
              </tptz:ContinuousMove>""",
          "ContinuousMoveResponse")

    check("S", "PTZ", "Stop", False,
          PTZ_SERVICE, NS_TPTZ,
          "Stop",
          f"""<tptz:Stop>
                <tptz:ProfileToken>{profile_token}</tptz:ProfileToken>
              </tptz:Stop>""",
          "StopResponse")

    # ── Profile S — Events ───────────────────────────────────────────────────
    check("S", "Events", "GetEventProperties", True,
          EVENT_SERVICE, NS_TEV,
          "GetEventProperties",
          "<tev:GetEventProperties/>",
          "GetEventPropertiesResponse")

    check("S", "Events", "CreatePullPointSubscription", True,
          EVENT_SERVICE, NS_TEV,
          "CreatePullPointSubscription",
          "<tev:CreatePullPointSubscription/>",
          "CreatePullPointSubscriptionResponse")

    check("S", "Events", "PullMessages", True,
          EVENT_SERVICE, NS_TEV,
          "PullMessages",
          """<tev:PullMessages>
               <tev:Timeout>PT5S</tev:Timeout>
               <tev:MessageLimit>10</tev:MessageLimit>
             </tev:PullMessages>""",
          "PullMessagesResponse")

    check("S", "Events", "Renew", True,
          EVENT_SERVICE, NS_TEV,
          "Renew",
          "<tev:Renew><tev:TerminationTime>PT10M</tev:TerminationTime></tev:Renew>",
          "RenewResponse")

    check("S", "Events", "Unsubscribe", True,
          EVENT_SERVICE, NS_TEV,
          "Unsubscribe",
          "<tev:Unsubscribe/>",
          "UnsubscribeResponse")

    # ── Profile T — Media2 ───────────────────────────────────────────────────
    check("T", "Media2", "GetProfiles", True,
          MEDIA2_SERVICE, NS_TR2,
          "GetProfiles",
          "<tr2:GetProfiles/>",
          "GetProfilesResponse")

    check("T", "Media2", "GetStreamUri", True,
          MEDIA2_SERVICE, NS_TR2,
          "GetStreamUri",
          f"""<tr2:GetStreamUri>
                <tr2:Protocol>RtspUnicast</tr2:Protocol>
                <tr2:ProfileToken>{profile_token}</tr2:ProfileToken>
              </tr2:GetStreamUri>""",
          "GetStreamUriResponse")

    check("T", "Media2", "GetSnapshotUri", True,
          MEDIA2_SERVICE, NS_TR2,
          "GetSnapshotUri",
          f"<tr2:GetSnapshotUri><tr2:ProfileToken>{profile_token}</tr2:ProfileToken></tr2:GetSnapshotUri>",
          "GetSnapshotUriResponse")

    check("T", "Media2", "GetVideoSources", False,
          MEDIA2_SERVICE, NS_TR2,
          "GetVideoSources",
          "<tr2:GetVideoSources/>",
          "GetVideoSourcesResponse")

    check("T", "Media2", "GetVideoEncoderConfigurations", False,
          MEDIA2_SERVICE, NS_TR2,
          "GetVideoEncoderConfigurations",
          "<tr2:GetVideoEncoderConfigurations/>",
          "GetVideoEncoderConfigurationsResponse")

    check("T", "Media2", "GetServiceCapabilities", False,
          MEDIA2_SERVICE, NS_TR2,
          "GetServiceCapabilities",
          "<tr2:GetServiceCapabilities/>",
          "GetServiceCapabilitiesResponse")

    # ── Profile G — Recording / Search / Replay ──────────────────────────────
    check("G", "Recording", "GetRecordings", False,
          RECORD_SERVICE, NS_TRC,
          "GetRecordings",
          "<trc:GetRecordings/>",
          "GetRecordingsResponse")

    check("G", "Recording", "GetRecordingSummary", False,
          RECORD_SERVICE, NS_TRC,
          "GetRecordingSummary",
          "<trc:GetRecordingSummary/>",
          "GetRecordingSummaryResponse")

    check("G", "Recording", "GetRecordingJobs", False,
          RECORD_SERVICE, NS_TRC,
          "GetRecordingJobs",
          "<trc:GetRecordingJobs/>",
          "GetRecordingJobsResponse")

    check("G", "Search", "FindRecordings", False,
          SEARCH_SERVICE, NS_TSE,
          "FindRecordings",
          "<tse:FindRecordings/>",
          "FindRecordingsResponse")

    check("G", "Search", "GetRecordingSearchResults", False,
          SEARCH_SERVICE, NS_TSE,
          "GetRecordingSearchResults",
          """<tse:GetRecordingSearchResults>
               <tse:SearchToken>dummy</tse:SearchToken>
               <tse:MaxResults>10</tse:MaxResults>
             </tse:GetRecordingSearchResults>""",
          "GetRecordingSearchResultsResponse")

    check("G", "Replay", "GetReplayUri", False,
          REPLAY_SERVICE, NS_TRP,
          "GetReplayUri",
          """<trp:GetReplayUri>
               <trp:RecordingToken>rec_1</trp:RecordingToken>
             </trp:GetReplayUri>""",
          "GetReplayUriResponse",
          custom_check=lambda root: (
              # Accept URI response (camera found) or NotPresent fault (no cameras yet)
              _has_response(root, "GetReplayUriResponse") or (
                  root is not None and b"NotPresent" in etree.tostring(root)
              ),
              "URI returned" if _has_response(root, "GetReplayUriResponse")
              else ("NotPresent fault (no recordings — expected on empty NVR)" if root is not None and b"NotPresent" in etree.tostring(root)
              else "No response")
          ))

    # GetReplayUri with StartTime — triggers time-shifted replay session
    _five_min_ago = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    check("G", "Replay", "GetReplayUri+StartTime", False,
          REPLAY_SERVICE, NS_TRP,
          "GetReplayUri",
          f"""<trp:GetReplayUri>
               <trp:RecordingToken>rec_1</trp:RecordingToken>
               <trp:StreamSetup>
                 <tt:Stream>RTP-Unicast</tt:Stream>
                 <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
               </trp:StreamSetup>
               <trp:StartTime>{_five_min_ago}</trp:StartTime>
             </trp:GetReplayUri>""",
          "GetReplayUriResponse",
          custom_check=lambda root: (
              # Accept either a URI response (segment found) or a NotPresent fault
              # (no recordings yet) — both are correct NVR behaviour.
              _has_response(root, "GetReplayUriResponse") or (
                  root is not None and b"NotPresent" in etree.tostring(root)
              ),
              "URI returned (segment found)" if _has_response(root, "GetReplayUriResponse")
              else ("NotPresent fault (no segments — expected on empty NVR)" if root is not None and b"NotPresent" in etree.tostring(root)
              else "No response")
          ))

    check("G", "Replay", "GetReplayConfiguration", False,
          REPLAY_SERVICE, NS_TRP,
          "GetReplayConfiguration",
          "<trp:GetReplayConfiguration/>",
          "GetReplayConfigurationResponse")

    check("G", "Replay", "SetReplayConfiguration", False,
          REPLAY_SERVICE, NS_TRP,
          "SetReplayConfiguration",
          """<trp:SetReplayConfiguration>
               <trp:Configuration>
                 <tt:SessionTimeout>PT5M</tt:SessionTimeout>
               </trp:Configuration>
             </trp:SetReplayConfiguration>""",
          "SetReplayConfigurationResponse")

    check("G", "Replay", "GetServiceCapabilities", False,
          REPLAY_SERVICE, NS_TRP,
          "GetServiceCapabilities",
          "<trp:GetServiceCapabilities/>",
          "GetServiceCapabilitiesResponse")

    # ── BaseNotification push subscriptions ──────────────────────────────────
    NS_WSNT = "http://docs.oasis-open.org/wsn/b-2"
    NS_WSA  = "http://www.w3.org/2005/08/addressing"

    check("S", "Events", "Subscribe (push)", False,
          EVENT_SERVICE, NS_TEV,
          "Subscribe",
          f"""<wsnt:Subscribe xmlns:wsnt="{NS_WSNT}" xmlns:wsa="{NS_WSA}">
                <wsnt:ConsumerReference>
                  <wsa:Address>http://127.0.0.1:59999/notify</wsa:Address>
                </wsnt:ConsumerReference>
                <wsnt:InitialTerminationTime>PT10M</wsnt:InitialTerminationTime>
              </wsnt:Subscribe>""",
          response_tag="SubscribeResponse",
          custom_check=lambda root: (
              _has_response(root, "SubscribeResponse"),
              "SubscribeResponse returned" if _has_response(root, "SubscribeResponse") else "No response or fault"
          ))

    # ── PullMessages with injected event (live event smoke test) ─────────────
    def _pull_with_inject(root_unused):
        """Create subscription, inject event, pull — verify event arrives."""
        try:
            # Step 1: create subscription
            pull_root = _call(EVENT_SERVICE,
                              f"{NS_TEV}/CreatePullPointSubscription",
                              "<tev:CreatePullPointSubscription/>")
            if pull_root is None or _has_fault(pull_root):
                return False, "CreatePullPointSubscription failed"
            # Step 2: inject event via test endpoint
            inject_url = f"{SCHEME}://{HOST}/onvif/test/inject_event?camera_id=conformance_test"
            r = requests.post(inject_url, timeout=TIMEOUT)
            if r.status_code not in (200, 201, 204):
                return False, f"inject_event returned {r.status_code}"
            # Step 3: pull — should see event immediately (queue has it)
            pull_resp = _call(EVENT_SERVICE,
                              f"{NS_TEV}/PullMessages",
                              """<tev:PullMessages>
                                   <tev:Timeout>PT5S</tev:Timeout>
                                   <tev:MessageLimit>10</tev:MessageLimit>
                                 </tev:PullMessages>""")
            if pull_resp is None or _has_fault(pull_resp):
                return False, "PullMessages failed after inject"
            xml_bytes = etree.tostring(pull_resp) if pull_resp is not None else b""
            has_msg = b"NotificationMessage" in xml_bytes
            return has_msg, "NotificationMessage in response" if has_msg else "No NotificationMessage — event not delivered"
        except Exception as e:
            return False, str(e)

    check("S", "Events", "PullMessages+LiveEvent", False,
          EVENT_SERVICE, NS_TEV,
          "PullMessages",
          "",
          custom_check=lambda _: _pull_with_inject(_))

    # ── Replay GetReplayConfiguration round-trip ──────────────────────────────
    def _replay_config_roundtrip(root_unused):
        """Set + Get replay config — verify value persists."""
        try:
            set_resp = _call(REPLAY_SERVICE,
                             f"{NS_TRP}/SetReplayConfiguration",
                             """<trp:SetReplayConfiguration>
                                  <trp:Configuration>
                                    <tt:SessionTimeout>PT3M</tt:SessionTimeout>
                                  </trp:Configuration>
                                </trp:SetReplayConfiguration>""")
            if set_resp is None or _has_fault(set_resp):
                return False, "SetReplayConfiguration fault"
            get_resp = _call(REPLAY_SERVICE,
                             f"{NS_TRP}/GetReplayConfiguration",
                             "<trp:GetReplayConfiguration/>")
            if get_resp is None or _has_fault(get_resp):
                return False, "GetReplayConfiguration fault after set"
            xml_bytes = etree.tostring(get_resp)
            # Expect PT3M (180s) in response
            ok = b"PT3M" in xml_bytes or b"PT180S" in xml_bytes
            return ok, "Timeout PT3M persisted" if ok else f"Unexpected value: {xml_bytes[200:300]}"
        except Exception as e:
            return False, str(e)

    check("G", "Replay", "ReplayConfig round-trip", False,
          REPLAY_SERVICE, NS_TRP,
          "SetReplayConfiguration",
          "",
          custom_check=lambda _: _replay_config_roundtrip(_))


# ── Print table ──────────────────────────────────────────────────────────────

def print_table(results: List[Result]):
    col_widths = [8, 10, 38, 5, 6, 50]
    headers = ["Profile", "Service", "Operation", "Mand.", "Status", "Note"]
    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"

    def row(cells):
        parts = []
        for c, w in zip(cells, col_widths):
            parts.append(str(c).ljust(w)[:w])
        return "| " + " | ".join(parts) + " |"

    print(sep)
    print(row(headers))
    print(sep)

    mandatory_fail = 0
    for r in results:
        mand = "YES" if r.mandatory else "no"
        print(row([r.profile, r.service, r.operation, mand, r.status, r.note]))
        if r.mandatory and r.status != PASS:
            mandatory_fail += 1

    print(sep)
    total = len(results)
    passed = sum(1 for r in results if r.status == PASS)
    failed = total - passed
    print(f"\nTotal: {total}  Passed: {passed}  Failed: {failed}  Mandatory failures: {mandatory_fail}")
    return mandatory_fail


if __name__ == "__main__":
    print(f"\nONVIF Conformance Check — target: {DEVICE_SERVICE}")
    print(f"Credentials: {USERNAME} / {'*' * len(PASSWORD)}\n")

    run_all()
    mandatory_fail = print_table(results)
    sys.exit(0 if mandatory_fail == 0 else 1)
