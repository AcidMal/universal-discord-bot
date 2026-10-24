from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.security import read_session
from shared.db import get_session_factory
from shared.settings import get_settings

router = APIRouter()

PRESENCES = {"online", "idle", "dnd", "invisible"}
ACTIVITIES = {"custom", "playing", "watching", "listening"}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def require_admin(request: Request) -> dict[str, Any]:
    session_data = read_session(request)
    if str(session_data.get("user_id")) not in get_settings().admin_id_set():
        raise HTTPException(status_code=403, detail="Bot admin only")
    return session_data


@router.get("/api/status")
async def cluster_status() -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        nodes = (
            await session.execute(
                text(
                    """
                    SELECT node_id, hostname, role, last_seen, claimed_shards,
                           EXTRACT(EPOCH FROM (now() - last_seen)) AS age_seconds
                    FROM cluster_nodes
                    ORDER BY role, hostname, node_id
                    """
                )
            )
        ).mappings().all()
        shards = (
            await session.execute(
                text(
                    """
                    SELECT shard_id, node_id, leased_until, gateway_status, latency_ms,
                           gateway_updated_at, leased_until > now() AS lease_valid
                    FROM shard_leases
                    ORDER BY shard_id
                    """
                )
            )
        ).mappings().all()

    grouped: dict[str, list[dict[str, Any]]] = {}
    ready = 0
    for shard in shards:
        node_id = shard["node_id"]
        status = str(shard["gateway_status"] or "unknown")
        if not shard["lease_valid"]:
            status = "expired" if node_id else "open"
        elif status == "ready":
            ready += 1
        grouped.setdefault(str(node_id) if node_id else "", []).append(
            {
                "shard_id": int(shard["shard_id"]),
                "status": status,
                "latency_ms": shard["latency_ms"],
                "lease_valid": bool(shard["lease_valid"]),
                "leased_until": _iso(shard["leased_until"]),
                "gateway_updated_at": _iso(shard["gateway_updated_at"]),
            }
        )

    payload_nodes = []
    online = 0
    for node in nodes:
        age = float(node["age_seconds"] or 0)
        if age < 20:
            status = "online"
            online += 1
        elif age < 60:
            status = "stale"
        else:
            status = "offline"
        node_id = str(node["node_id"])
        payload_nodes.append(
            {
                "node_id": node_id,
                "hostname": node["hostname"] or "unknown",
                "role": node["role"] or "gateway",
                "status": status,
                "age_seconds": round(age, 1),
                "last_seen": _iso(node["last_seen"]),
                "shards": grouped.get(node_id, []),
            }
        )

    unassigned = grouped.get("", [])
    return {
        "summary": {
            "nodes_online": online,
            "nodes_total": len(payload_nodes),
            "shards_ready": ready,
            "shards_total": len(shards),
        },
        "nodes": payload_nodes,
        "unassigned_shards": unassigned,
    }


class BotSettingsBody(BaseModel):
    presence: str
    activity_type: str
    status_text: str = Field(default="", max_length=128)


@router.get("/api/admin/bot")
async def get_bot_settings(request: Request) -> dict[str, str]:
    require_admin(request)
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT presence, activity_type, status_text FROM bot_profile WHERE id = 1")
            )
        ).mappings().first()
    if row is None:
        return {"presence": "online", "activity_type": "custom", "status_text": ""}
    return {
        "presence": str(row["presence"]),
        "activity_type": str(row["activity_type"]),
        "status_text": str(row["status_text"] or ""),
    }


@router.put("/api/admin/bot")
async def put_bot_settings(body: BotSettingsBody, request: Request) -> dict[str, str]:
    require_admin(request)
    presence = body.presence.strip().lower()
    activity = body.activity_type.strip().lower()
    if presence not in PRESENCES:
        raise HTTPException(status_code=422, detail="Presence must be online, idle, dnd, or invisible")
    if activity not in ACTIVITIES:
        raise HTTPException(status_code=422, detail="Activity must be custom, playing, watching, or listening")
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO bot_profile (id, presence, activity_type, status_text, updated_at)
                VALUES (1, :presence, :activity, :status_text, now())
                ON CONFLICT (id) DO UPDATE
                SET presence = EXCLUDED.presence,
                    activity_type = EXCLUDED.activity_type,
                    status_text = EXCLUDED.status_text,
                    updated_at = now()
                """
            ),
            {"presence": presence, "activity": activity, "status_text": body.status_text.strip()},
        )
        await session.execute(text("SELECT pg_notify('bot_settings', '')"))
        await session.commit()
    return {"presence": presence, "activity_type": activity, "status_text": body.status_text.strip()}


async def forget_api_node(node_id: str) -> None:
    if not node_id:
        return
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM cluster_nodes WHERE node_id = :node AND role = 'api'"),
            {"node": node_id},
        )
        await session.commit()


async def record_api_heartbeat(node_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO cluster_nodes (node_id, hostname, last_seen, claimed_shards, role)
                VALUES (:node, :hostname, now(), '[]'::jsonb, 'api')
                ON CONFLICT (node_id) DO UPDATE
                SET hostname = EXCLUDED.hostname, last_seen = now(), role = 'api'
                """
            ),
            {"node": node_id, "hostname": socket.gethostname()},
        )
        await session.commit()
