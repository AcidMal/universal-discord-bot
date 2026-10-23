"""Pure Twitch alert helpers. No network."""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime
from typing import Any

_LOGIN = re.compile(r"[a-z0-9_]{2,25}")


def normalize_login(raw: str) -> str:
    text = raw.strip()
    for prefix in ("https://", "http://"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
    if text.lower().startswith("www."):
        text = text[4:]
    lowered = text.lower()
    marker = "twitch.tv/"
    if marker in lowered:
        text = text[lowered.index(marker) + len(marker) :]
    text = text.split("/")[0].split("?")[0].split("#")[0].lstrip("@").lower()
    if _LOGIN.fullmatch(text) is None:
        raise ValueError("Use a Twitch login like shroud, or a twitch.tv link")
    return text


def parse_twitch_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stream_thumbnail(login: str, helix_template: str | None, started_at: datetime) -> str:
    if helix_template and "{width}" in helix_template:
        url = helix_template.replace("{width}", "1280").replace("{height}", "720")
    else:
        url = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login.lower()}-1280x720.jpg"
    stamp = str(int(started_at.timestamp()))
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}t={stamp}"


def live_embed(*, accent: str, title: str, channel_name: str, login: str, thumbnail_url: str) -> dict[str, Any]:
    color_hex = accent.lstrip("#")
    link = f"https://twitch.tv/{login}"
    stream_title = (title or "Live now").strip()[:256] or "Live now"
    name = (channel_name or login).strip()[:256]
    return {
        "title": stream_title,
        "url": link,
        "color": int(color_hex, 16) if color_hex else 0,
        "author": {"name": name, "url": link},
        "fields": [{"name": "Channel", "value": f"[{name}]({link})", "inline": True}],
        "image": {"url": thumbnail_url},
        "footer": {"text": "Live on Twitch"},
    }


def verify_eventsub_signature(*, secret: str, message_id: str, timestamp: str, body: bytes, signature: str) -> bool:
    if not secret or not signature.startswith("sha256="):
        return False
    digest = hmac.new(
        secret.encode("utf-8"),
        message_id.encode("utf-8") + timestamp.encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature.removeprefix("sha256="))
