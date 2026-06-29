"""Pulse — first-party notifications and launch comms."""

from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List

from creation.config import UserSecrets
from creation.services.types import OpsResult

INBOX_DIR = Path.home() / ".creation" / "pulse"
SOCIAL_DIR = INBOX_DIR / "social"


@dataclass
class MarketingResult:
    email_sent: bool = False
    social_posted: bool = False
    detail: str = ""
    channels: List[str] = field(default_factory=list)


class PulseNotify:
    def __init__(self, secrets: UserSecrets) -> None:
        self.secrets = secrets
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        SOCIAL_DIR.mkdir(parents=True, exist_ok=True)

    def send(self, subject: str, body: str, to: str) -> OpsResult:
        record = {
            "to": to,
            "subject": subject,
            "body": body,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = INBOX_DIR / f"{stamp}.json"
        path.write_text(json.dumps(record, indent=2))

        if self.secrets.smtp_host and self.secrets.smtp_user:
            try:
                self._smtp_send(to, subject, body)
                return OpsResult(True, f"Pulse email sent to {to}", {"path": str(path)})
            except Exception as exc:
                return OpsResult(False, str(exc), {"path": str(path)})

        return OpsResult(True, f"Pulse saved notification for {to}", {"path": str(path), "inbox": True})

    def _smtp_send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject[:200]
        msg["From"] = self.secrets.smtp_from or self.secrets.smtp_user
        msg["To"] = to
        msg.set_content(body[:15000])
        with smtplib.SMTP(self.secrets.smtp_host, self.secrets.smtp_port) as smtp:
            if self.secrets.smtp_tls:
                smtp.starttls()
            if self.secrets.smtp_user and self.secrets.smtp_password:
                smtp.login(self.secrets.smtp_user, self.secrets.smtp_password)
            smtp.send_message(msg)


def build_launch_email_html(product_name: str, tagline: str, live_url: str) -> str:
    return f"""<!DOCTYPE html><html><body style="font-family:sans-serif">
<h1>{product_name}</h1><p>{tagline}</p>
<p><a href="{live_url}">Try it live</a></p>
<p>— Built with Creation</p></body></html>"""


def build_launch_social_post(product_name: str, tagline: str, live_url: str) -> str:
    return f"Shipped {product_name} — {tagline} {live_url} #buildinpublic"


def launch_marketing(secrets: UserSecrets, *, product_name: str, tagline: str, live_url: str) -> MarketingResult:
    if not secrets.marketing_enabled:
        return MarketingResult(detail="marketing disabled")

    pulse = PulseNotify(secrets)
    result = MarketingResult()
    channels: List[str] = []

    if secrets.marketing_to:
        html = build_launch_email_html(product_name, tagline, live_url)
        r = pulse.send(f"Launch: {product_name}", html, secrets.marketing_to)
        result.email_sent = r.success
        if r.success:
            channels.append("email")

    post = build_launch_social_post(product_name, tagline, live_url)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    social_path = SOCIAL_DIR / f"{stamp}.txt"
    social_path.write_text(post)
    result.social_posted = True
    channels.append("social-draft")

    result.channels = channels
    result.detail = f"Pulse queued: {', '.join(channels)}"
    return result
