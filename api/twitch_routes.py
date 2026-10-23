from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response

from shared.settings import get_settings
from shared.twitch import handle_eventsub_notification, mark_subscription_revoked
from shared.twitch_format import verify_eventsub_signature

log = logging.getLogger("api.twitch")
router = APIRouter()


@router.post("/twitch/eventsub")
async def eventsub(request: Request, background: BackgroundTasks) -> Response:
    secret = get_settings().twitch_eventsub_secret
    raw = await request.body()
    if not verify_eventsub_signature(
        secret=secret,
        message_id=request.headers.get("Twitch-Eventsub-Message-Id", ""),
        timestamp=request.headers.get("Twitch-Eventsub-Message-Timestamp", ""),
        body=raw,
        signature=request.headers.get("Twitch-Eventsub-Message-Signature", ""),
    ):
        return Response(status_code=403)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return Response(status_code=400)
    message_type = request.headers.get("Twitch-Eventsub-Message-Type", "")
    if message_type == "webhook_callback_verification":
        challenge = str(payload.get("challenge") or "")
        return Response(content=challenge, media_type="text/plain")
    if message_type == "notification":
        background.add_task(handle_eventsub_notification, payload)
    elif message_type == "revocation":
        subscription_id = str((payload.get("subscription") or {}).get("id") or "")
        log.warning("Twitch revoked EventSub %s", subscription_id)
        if subscription_id:
            background.add_task(mark_subscription_revoked, subscription_id)
    return Response(status_code=204)
