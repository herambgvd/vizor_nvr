# =============================================================================
# SMTP Email Service — transactional alerts for NVR events
# =============================================================================
# Supports TLS (port 587) and SSL (port 465).
# Settings are read from the database so they can be changed at runtime
# without a server restart.
# =============================================================================

import asyncio
import logging
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------

_STYLE = """
<style>
  body { font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }
  .container { max-width: 600px; margin: 30px auto; background: #fff;
               border-radius: 8px; overflow: hidden;
               box-shadow: 0 2px 8px rgba(0,0,0,.12); }
  .header { background: #1a1a2e; color: #fff; padding: 24px 32px; }
  .header h1 { margin: 0; font-size: 20px; }
  .header p  { margin: 4px 0 0; font-size: 13px; color: #aaa; }
  .body   { padding: 24px 32px; color: #333; }
  .detail { background: #f8f8f8; border-left: 4px solid #e84545;
            padding: 12px 16px; border-radius: 4px; margin: 16px 0; }
  .detail.online { border-color: #28a745; }
  .detail.warning { border-color: #ffc107; }
  .footer { background: #f0f0f0; padding: 12px 32px; font-size: 11px;
            color: #999; text-align: center; }
  .badge  { display: inline-block; padding: 4px 10px; border-radius: 12px;
            font-size: 12px; font-weight: bold; }
  .badge.offline  { background: #ffe5e5; color: #c0392b; }
  .badge.online   { background: #e5ffe9; color: #196f3d; }
  .badge.warning  { background: #fff8e1; color: #856404; }
  .badge.error    { background: #ffe5e5; color: #c0392b; }
</style>
"""


def _base_html(title: str, body_html: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"""<!DOCTYPE html><html><head>{_STYLE}</head><body>
<div class="container">
  <div class="header">
    <h1>Vizor NVR — {title}</h1>
    <p>{ts}</p>
  </div>
  <div class="body">{body_html}</div>
  <div class="footer">Vizor NVR Surveillance System &mdash; Automated Alert</div>
</div></body></html>"""


TEMPLATES = {
    "camera_offline": lambda d: _base_html(
        "Camera Offline",
        f"""<p>Camera <strong>{d.get('camera_name', d.get('camera_id'))}</strong>
        has gone <span class="badge offline">OFFLINE</span>.</p>
        <div class="detail">
          <b>Camera&nbsp;ID:</b> {d.get('camera_id')}<br>
          <b>Location:</b> {d.get('location', 'N/A')}<br>
          <b>Last&nbsp;seen:</b> {d.get('last_online', 'Unknown')}
        </div>
        <p>Please verify network connectivity and camera power.</p>"""
    ),
    "camera_online": lambda d: _base_html(
        "Camera Online",
        f"""<p>Camera <strong>{d.get('camera_name', d.get('camera_id'))}</strong>
        is back <span class="badge online">ONLINE</span>.</p>
        <div class="detail online">
          <b>Camera&nbsp;ID:</b> {d.get('camera_id')}<br>
          <b>Location:</b> {d.get('location', 'N/A')}
        </div>"""
    ),
    "recording_error": lambda d: _base_html(
        "Recording Error",
        f"""<p>Recording failure on camera
        <strong>{d.get('camera_name', d.get('camera_id'))}</strong>.</p>
        <div class="detail">
          <b>Camera&nbsp;ID:</b> {d.get('camera_id')}<br>
          <b>Error:</b> {d.get('error', 'Unknown error')}<br>
          <b>Retry&nbsp;count:</b> {d.get('retry_count', '?')}
        </div>
        <p>The system will attempt to restart the recording automatically.</p>"""
    ),
    "storage_low": lambda d: _base_html(
        "Storage Low Warning",
        f"""<p>Storage space is running low on the NVR system.</p>
        <div class="detail warning">
          <b>Used:</b> {d.get('used_gb', '?')} GB<br>
          <b>Total:</b> {d.get('total_gb', '?')} GB<br>
          <b>Free:</b> {d.get('free_gb', '?')} GB<br>
          <b>Usage:</b> {d.get('percent', '?')}%
        </div>
        <p>Consider adjusting retention settings or adding storage capacity.</p>"""
    ),
    "storage_full": lambda d: _base_html(
        "Storage Full — Recording May Stop",
        f"""<p><strong>Critical:</strong> Storage is full. New recordings may fail.</p>
        <div class="detail">
          <b>Used:</b> {d.get('used_gb', '?')} GB / {d.get('total_gb', '?')} GB
        </div>
        <p>Immediate action required: free up disk space or enable auto-retention.</p>"""
    ),
    "recording_gap": lambda d: _base_html(
        "Recording Gap Detected",
        f"""<p>No new recording segments detected for camera
        <strong>{d.get('camera_name', d.get('camera_id'))}</strong>.</p>
        <div class="detail">
          <b>Camera&nbsp;ID:</b> {d.get('camera_id')}<br>
          <b>Last&nbsp;segment:</b> {d.get('last_segment_time', 'Unknown')}<br>
          <b>Gap&nbsp;duration:</b> {d.get('gap_seconds', '?')} seconds
        </div>
        <p>The system is attempting to restore the recording stream.</p>"""
    ),
    "test": lambda d: _base_html(
        "Test Notification",
        f"""<p>This is a test email from your Vizor NVR system.</p>
        <div class="detail online">
          <b>System:</b> {d.get('system_name', 'Vizor NVR')}<br>
          <b>Status:</b> Email notifications are working correctly.
        </div>"""
    ),
    "motion_detected": lambda d: _base_html(
        "Motion Detected",
        f"""<p>Motion detected on camera <strong>{d.get('camera_name', d.get('camera_id'))}</strong>.</p>
        <div class="detail warning">
          <b>Camera&nbsp;ID:</b> {d.get('camera_id')}<br>
          <b>Event:</b> {d.get('title', 'Motion detected')}<br>
          <b>Description:</b> {d.get('description', 'N/A')}
        </div>
        {f'<p><img src="cid:snapshot" style="max-width:100%;border-radius:4px;"/></p>' if d.get('snapshot_path') else ''}
        <p>Review the event in the NVR playback interface.</p>"""
    ),
}

_SUBJECTS = {
    "camera_offline":  "Vizor NVR Alert — Camera Offline: {camera_name}",
    "camera_online":   "Vizor NVR — Camera Online: {camera_name}",
    "recording_error": "Vizor NVR Alert — Recording Error: {camera_name}",
    "storage_low":     "Vizor NVR Warning — Storage Low ({percent}% used)",
    "storage_full":    "Vizor NVR CRITICAL — Storage Full",
    "recording_gap":   "Vizor NVR Alert — Recording Gap: {camera_name}",
    "test":            "Vizor NVR — Test Notification",
    "motion_detected": "Vizor NVR Alert — Motion Detected: {camera_name}",
}


# ---------------------------------------------------------------------------
# SMTP Client
# ---------------------------------------------------------------------------

class SMTPEmailService:
    """
    Sends HTML emails via SMTP.
    Config is fetched from the DB on each call so changes take immediate effect.
    """

    async def send_event_email(
        self,
        event_type: str,
        data: dict,
        recipients: List[str],
        smtp_config: dict,
    ) -> bool:
        """
        Render and dispatch an event email with optional snapshot attachment.

        Args:
            event_type: Key into TEMPLATES / _SUBJECTS.
            data:        Template data dict. May contain 'snapshot_path'.
            recipients:  List of destination email addresses.
            smtp_config: {host, port, username, password, use_tls,
                          use_ssl, from_email, from_name}.
        Returns:
            True on success, False on failure.
        """
        template_fn = TEMPLATES.get(event_type)
        if not template_fn:
            logger.warning(f"No email template for event: {event_type}")
            return False

        subject_tpl = _SUBJECTS.get(event_type, "Vizor NVR Notification")
        try:
            subject = subject_tpl.format(**{k: data.get(k, "") for k in data})
        except KeyError:
            subject = subject_tpl

        html_body = template_fn(data)
        snapshot_path = data.get("snapshot_path")

        ok, _reason = await asyncio.to_thread(
            self._send_sync,
            smtp_config=smtp_config,
            recipients=recipients,
            subject=subject,
            html_body=html_body,
            snapshot_path=snapshot_path,
        )
        return ok

    async def send_event_email_detailed(
        self,
        event_type: str,
        data: dict,
        recipients: List[str],
        smtp_config: dict,
    ) -> tuple:
        """Like send_event_email but returns (ok, reason) so the test endpoint can
        give operator-friendly feedback (connect vs auth vs recipient rejected)
        without leaking raw SMTP exception text."""
        template_fn = TEMPLATES.get(event_type)
        if not template_fn:
            return False, "unsupported"

        subject_tpl = _SUBJECTS.get(event_type, "Vizor NVR Notification")
        try:
            subject = subject_tpl.format(**{k: data.get(k, "") for k in data})
        except KeyError:
            subject = subject_tpl

        html_body = template_fn(data)
        snapshot_path = data.get("snapshot_path")

        return await asyncio.to_thread(
            self._send_sync,
            smtp_config=smtp_config,
            recipients=recipients,
            subject=subject,
            html_body=html_body,
            snapshot_path=snapshot_path,
        )

    def _send_sync(
        self,
        smtp_config: dict,
        recipients: List[str],
        subject: str,
        html_body: str,
        snapshot_path: Optional[str] = None,
    ) -> tuple:
        """Blocking send — runs in a thread pool via asyncio.to_thread.

        Returns (ok: bool, reason: str). ``reason`` is a short, non-technical
        category ("ok", "not_configured", "connect", "auth", "recipient",
        "send") — never raw SMTP exception text — so callers can map it to clean
        operator-facing copy."""
        host     = smtp_config.get("host", "")
        port     = int(smtp_config.get("port", 587))
        username = smtp_config.get("username", "")
        password = smtp_config.get("password", "")
        use_tls  = str(smtp_config.get("use_tls", "true")).lower() == "true"
        use_ssl  = str(smtp_config.get("use_ssl", "false")).lower() == "true"
        from_email = smtp_config.get("from_email") or username
        from_name  = smtp_config.get("from_name", "Vizor NVR")

        if not host or not recipients:
            logger.warning("SMTP not configured or no recipients — skipping email")
            return False, "not_configured"

        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"]    = f"{from_name} <{from_email}>"
        msg["To"]      = ", ".join(recipients)

        # HTML part
        msg_alt = MIMEMultipart("alternative")
        msg.attach(msg_alt)
        msg_alt.attach(MIMEText(html_body, "html", "utf-8"))

        # Snapshot attachment
        if snapshot_path and os.path.exists(snapshot_path):
            try:
                with open(snapshot_path, "rb") as f:
                    img_data = f.read()
                img = MIMEImage(img_data)
                img.add_header("Content-ID", "<snapshot>")
                img.add_header("Content-Disposition", "inline", filename="snapshot.jpg")
                msg.attach(img)
            except Exception as e:
                logger.warning(f"Failed to attach snapshot: {e}")

        try:
            if use_ssl:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as srv:
                    if username:
                        srv.login(username, password)
                    srv.sendmail(from_email, recipients, msg.as_string())
            else:
                with smtplib.SMTP(host, port, timeout=15) as srv:
                    if use_tls:
                        srv.starttls(context=ssl.create_default_context())
                    if username:
                        srv.login(username, password)
                    srv.sendmail(from_email, recipients, msg.as_string())

            logger.info(f"Email sent [{subject}] → {recipients}")
            return True, "ok"

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed — check username/password")
            return False, "auth"
        except smtplib.SMTPConnectError as e:
            logger.error(f"SMTP connect error ({host}:{port}): {e}")
            return False, "connect"
        except smtplib.SMTPRecipientsRefused:
            logger.error("SMTP recipients refused — check the recipient addresses")
            return False, "recipient"
        except smtplib.SMTPServerDisconnected as e:
            logger.error(f"SMTP server disconnected ({host}:{port}): {e}")
            return False, "connect"
        except (OSError, ConnectionError, TimeoutError) as e:
            # Host unreachable / DNS failure / refused / timeout.
            logger.error(f"SMTP connect error ({host}:{port}): {e}")
            return False, "connect"
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False, "send"


# Module singleton
smtp_service = SMTPEmailService()
