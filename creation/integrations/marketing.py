"""Launch marketing — Pulse (first-party)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from creation.config import UserSecrets
from creation.services.pulse.notify import PulseNotify


@dataclass
class MarketingResult:
    success: bool = False
    provider: str = "pulse"
    message: str = ""
    broadcast_id: str = ""
    emails_sent: int = 0
    social_post_id: str = ""
    platforms: List[str] = field(default_factory=list)
    post_urls: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "provider": self.provider,
            "message": self.message,
            "broadcast_id": self.broadcast_id,
            "emails_sent": self.emails_sent,
            "social_post_id": self.social_post_id,
            "platforms": self.platforms,
            "post_urls": self.post_urls,
            "channels": self.channels,
        }


_PLATFORM_ALIASES = {"x": "twitter", "twitter": "twitter", "linkedin": "linkedin"}


def _parse_platforms(raw: str) -> list[str]:
    text = (raw or "").strip().lower()
    if not text or text == "all":
        return ["all"]
    out: list[str] = []
    for part in re.split(r"[\s,]+", text):
        mapped = _PLATFORM_ALIASES.get(part.strip(), part.strip())
        if mapped and mapped not in out:
            out.append(mapped)
    return out or ["twitter", "linkedin"]


def build_launch_email_html(
    product_name: str,
    tagline: str = "",
    idea: str = "",
    deploy_url: str = "",
    github_url: str = "",
    **_: object,
) -> str:
    live = deploy_url or github_url or "#"
    return f"""<!DOCTYPE html><html><body style="font-family:sans-serif">
<h1>{product_name}</h1><p>{tagline or idea}</p>
<p><a href="{live}">Try it live</a></p>
<p>— Built with Creation</p></body></html>"""


def build_launch_social_post(
    product_name: str,
    tagline: str = "",
    idea: str = "",
    deploy_url: str = "",
    **_: object,
) -> str:
    return f"Shipped {product_name} — {tagline or idea} {deploy_url}".strip()


def launch_marketing(
    secrets: UserSecrets | None = None,
    *,
    product_name: str = "",
    tagline: str = "",
    live_url: str = "",
    deploy_url: str = "",
    marketing_to: str = "",
    demo: bool = False,
    social_post: str = "",
    **kwargs: object,
) -> MarketingResult:
    from creation.config import UserSecrets as US

    sec = secrets if isinstance(secrets, UserSecrets) else US()
    if demo:
        return MarketingResult(success=True, message="demo", channels=["email", "social"])
    if not sec.marketing_enabled and not marketing_to and not sec.marketing_to:
        return MarketingResult(success=False, message="Marketing not configured")

    pulse = PulseNotify(sec)
    result = MarketingResult(success=True, provider="pulse")
    channels: List[str] = []
    recipient = (marketing_to or sec.marketing_to or sec.notify_email).strip()
    url = live_url or deploy_url
    name = product_name or "Product"

    if recipient:
        html = build_launch_email_html(name, tagline, deploy_url=url)
        if pulse.send(f"Launch: {name}", html, recipient).success:
            result.emails_sent = 1
            channels.append("email")

    post = social_post or build_launch_social_post(name, tagline, deploy_url=url)
    from datetime import datetime, timezone
    from pathlib import Path

    social_dir = Path.home() / ".creation" / "pulse" / "social"
    social_dir.mkdir(parents=True, exist_ok=True)
    path = social_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(post)
    result.social_post_id = str(path)
    channels.append("social")
    result.channels = channels
    result.message = f"Pulse queued: {', '.join(channels)}"
    return result


def _post_ayrshare(*args, **kwargs) -> MarketingResult:
    return MarketingResult(success=True, provider="pulse", message="social draft saved", channels=["social"])
