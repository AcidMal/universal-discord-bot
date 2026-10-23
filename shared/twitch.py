"""Twitch Helix, EventSub, and Discord live announcements."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.db import get_session_factory
from shared.models import GuildTheme, TwitchAlert, TwitchSubscription
from shared.settings import get_settings
from shared.theme import PRESETS
from shared.twitch_format import live_embed, parse_twitch_time, stream_thumbnail

log = logging.getLogger("twitch")

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
EVENT_TYPES = ("stream.online", "stream.offline")
_token = ""
_token_expires = 0.0


class TwitchError(RuntimeError):
    pass


def twitch_configured() -> bool:
    settings = get_settings()
    return bool(settings.twitch_client_id and settings.twitch_client_secret)


def instant_webhook_available() -> bool:
    settings = get_settings()
    host = (urlparse(settings.public_url).hostname or "").lower()
    return bool(
        settings.twitch_eventsub_secret
        and settings.public_url.startswith("https://")
        and host not in {"localhost", "127.0.0.1"}
    )


def eventsub_callback() -> str:
    return f"{get_settings().public_url}/twitch/eventsub"


async def app_token() -> str:
    global _token, _token_expires
    if _token and time.time() < _token_expires:
        return _token
    settings = get_settings()
    if not twitch_configured():
        raise TwitchError("Set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.twitch_client_id,
                "client_secret": settings.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        )
    if response.status_code >= 400:
        raise TwitchError(f"Twitch token request failed ({response.status_code})")
    payload = response.json()
    _token = str(payload["access_token"])
    _token_expires = time.time() + max(60, int(payload.get("expires_in") or 3600) - 60)
    return _token


async def _helix(method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
    settings = get_settings()
    token = await app_token()
    headers = {"Client-Id": settings.twitch_client_id, "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(method, f"{HELIX}{path}", headers=headers, params=params, json=json)
    if response.status_code >= 400:
        raise TwitchError(f"Twitch {response.status_code} on {path}: {response.text[:240]}")
    if not response.content:
        return None
    return response.json()


async def lookup_user(login: str) -> dict[str, str]:
    payload = await _helix("GET", "/users", params={"login": login})
    rows = list((payload or {}).get("data") or [])
    if not rows:
        raise TwitchError(f"Twitch user `{login}` was not found")
    row = rows[0]
    return {"id": str(row["id"]), "login": str(row["login"]), "name": str(row.get("display_name") or row["login"])}


async def fetch_streams(user_ids: list[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for start in range(0, len(user_ids), 100):
        chunk = user_ids[start : start + 100]
        params = [("user_id", user_id) for user_id in chunk]
        payload = await _helix("GET", "/streams", params=params)
        found.extend((payload or {}).get("data") or [])
    return found


async def fetch_stream(user_id: str) -> dict[str, Any] | None:
    rows = await fetch_streams([user_id])
    return rows[0] if rows else None


async def ensure_eventsub(broadcaster_id: str) -> str | None:
    """Subscribe to online and offline. Returns a note when instant push is unavailable."""
    if not instant_webhook_available():
        return (
            "Instant push needs a public https PUBLIC_URL and TWITCH_EVENTSUB_SECRET. "
            "Until then this channel is checked every 10 seconds."
        )
    settings = get_settings()
    callback = eventsub_callback()
    for event_type in EVENT_TYPES:
        body = {
            "type": event_type,
            "version": "1",
            "condition": {"broadcaster_user_id": broadcaster_id},
            "transport": {
                "method": "webhook",
                "callback": callback,
                "secret": settings.twitch_eventsub_secret,
            },
        }
        try:
            payload = await _helix("POST", "/eventsub/subscriptions", json=body)
        except TwitchError as exc:
            message = str(exc)
            if "409" in message:
                continue
            log.warning("eventsub %s for %s failed: %s", event_type, broadcaster_id, exc)
            return f"Saved the alert. Twitch push failed ({exc}). Checking every 10 seconds."
        data = list((payload or {}).get("data") or [])
        subscription_id = str(data[0]["id"]) if data else ""
        status = str(data[0].get("status") or "pending") if data else "pending"
        factory = get_session_factory()
        async with factory() as session:
            stmt = pg_insert(TwitchSubscription).values(
                broadcaster_id=broadcaster_id,
                event_type=event_type,
                subscription_id=subscription_id,
                status=status,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["broadcaster_id", "event_type"],
                set_={"subscription_id": stmt.excluded.subscription_id, "status": stmt.excluded.status},
            )
            await session.execute(stmt)
            await session.commit()
    return None


async def delete_eventsub(broadcaster_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(TwitchSubscription).where(TwitchSubscription.broadcaster_id == broadcaster_id)
                )
            ).all()
        )
        subscription_ids = [row.subscription_id for row in rows if row.subscription_id]
        for row in rows:
            await session.delete(row)
        await session.commit()
    for subscription_id in subscription_ids:
        try:
            await _helix("DELETE", "/eventsub/subscriptions", params={"id": subscription_id})
        except TwitchError:
            log.warning("could not delete EventSub %s", subscription_id)


async def mark_subscription_revoked(subscription_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                UPDATE twitch_subscriptions
                SET status = 'revoked'
                WHERE subscription_id = :subscription_id
                """
            ),
            {"subscription_id": subscription_id},
        )
        await session.commit()


async def _claim(broadcaster_id: str, started_at: datetime) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO twitch_live_state (broadcaster_id, live, started_at)
                VALUES (:broadcaster_id, true, :started_at)
                ON CONFLICT (broadcaster_id) DO UPDATE
                SET live = true, started_at = EXCLUDED.started_at
                WHERE twitch_live_state.live = false
                   OR twitch_live_state.started_at IS NULL
                   OR ABS(EXTRACT(EPOCH FROM (twitch_live_state.started_at - EXCLUDED.started_at))) > 30
                RETURNING broadcaster_id
                """
            ),
            {"broadcaster_id": broadcaster_id, "started_at": started_at},
        )
        claimed = result.first() is not None
        await session.commit()
        return claimed


async def mark_offline(broadcaster_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                UPDATE twitch_live_state
                SET live = false
                WHERE broadcaster_id = :broadcaster_id AND live = true
                """
            ),
            {"broadcaster_id": broadcaster_id},
        )
        await session.commit()


async def _alerts(broadcaster_id: str) -> list[tuple[int, int]]:
    factory = get_session_factory()
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(TwitchAlert).where(
                        TwitchAlert.twitch_user_id == broadcaster_id,
                        TwitchAlert.enabled.is_(True),
                    )
                )
            ).all()
        )
        return [(row.guild_id, row.discord_channel_id) for row in rows]


async def _accent(guild_id: int) -> str:
    factory = get_session_factory()
    async with factory() as session:
        theme = await session.get(GuildTheme, guild_id)
        if theme is None:
            return PRESETS["midnight"].accent
        return theme.accent


async def _post_discord(channel_id: int, embed: dict[str, Any]) -> None:
    token = get_settings().discord_token
    if not token:
        raise TwitchError("DISCORD_TOKEN is empty")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            json={"embeds": [embed]},
        )
    if response.status_code >= 400:
        raise TwitchError(f"Discord rejected the live alert ({response.status_code})")


async def announce_live(
    *,
    broadcaster_id: str,
    login: str,
    display_name: str,
    started_at: datetime,
    title: str | None = None,
    thumbnail_template: str | None = None,
) -> None:
    if not await _claim(broadcaster_id, started_at):
        return
    stream_title = title
    template = thumbnail_template
    if stream_title is None:
        stream = None
        for _ in range(3):
            try:
                stream = await fetch_stream(broadcaster_id)
            except TwitchError:
                log.exception("helix stream lookup failed for %s", login)
                break
            if stream:
                break
            await asyncio.sleep(1)
        if stream:
            stream_title = str(stream.get("title") or "Live now")
            template = str(stream.get("thumbnail_url") or "")
            display_name = str(stream.get("user_name") or display_name)
            login = str(stream.get("user_login") or login)
            if stream.get("started_at"):
                started_at = parse_twitch_time(str(stream["started_at"]))
    alerts = await _alerts(broadcaster_id)
    if not alerts:
        return
    thumbnail = stream_thumbnail(login, template, started_at)
    failures = 0
    for guild_id, channel_id in alerts:
        embed = live_embed(
            accent=await _accent(guild_id),
            title=stream_title or "Live now",
            channel_name=display_name,
            login=login,
            thumbnail_url=thumbnail,
        )
        try:
            await _post_discord(channel_id, embed)
        except Exception:
            failures += 1
            log.exception("live alert failed for guild %s channel %s", guild_id, channel_id)
    if failures == len(alerts):
        await mark_offline(broadcaster_id)


async def handle_eventsub_notification(payload: dict[str, Any]) -> None:
    subscription = payload.get("subscription") or {}
    event = payload.get("event") or {}
    event_type = str(subscription.get("type") or "")
    broadcaster_id = str(event.get("broadcaster_user_id") or "")
    if not broadcaster_id:
        return
    if event_type == "stream.offline":
        await mark_offline(broadcaster_id)
        return
    if event_type != "stream.online":
        return
    if str(event.get("type") or "live") != "live":
        return
    started_raw = str(event.get("started_at") or "")
    if not started_raw:
        return
    await announce_live(
        broadcaster_id=broadcaster_id,
        login=str(event.get("broadcaster_user_login") or ""),
        display_name=str(event.get("broadcaster_user_name") or ""),
        started_at=parse_twitch_time(started_raw),
    )


async def poll_live_channels() -> None:
    if not twitch_configured():
        return
    factory = get_session_factory()
    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(TwitchAlert.twitch_user_id, TwitchAlert.twitch_login).where(TwitchAlert.enabled.is_(True))
                )
            ).all()
        )
    watched = {str(user_id): str(login) for user_id, login in rows}
    if not watched:
        return
    streams = await fetch_streams(list(watched))
    live_ids: set[str] = set()
    for stream in streams:
        user_id = str(stream.get("user_id") or "")
        started_raw = str(stream.get("started_at") or "")
        if not user_id or not started_raw:
            continue
        live_ids.add(user_id)
        await announce_live(
            broadcaster_id=user_id,
            login=str(stream.get("user_login") or watched.get(user_id) or ""),
            display_name=str(stream.get("user_name") or ""),
            started_at=parse_twitch_time(started_raw),
            title=str(stream.get("title") or "Live now"),
            thumbnail_template=str(stream.get("thumbnail_url") or ""),
        )
    for user_id in watched:
        if user_id not in live_ids:
            await mark_offline(user_id)
