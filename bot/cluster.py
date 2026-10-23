"""Postgres shard leases and guild cache invalidation. No Redis."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import socket

import aiohttp
from sqlalchemy import text

from shared.db import get_session_factory
from shared.settings import get_settings

log = logging.getLogger("bot.cluster")

GATEWAY_URL = "https://discord.com/api/v10/gateway/bot"


def asyncpg_dsn(database_url: str | None = None) -> str:
    url = database_url or get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def recommended_shard_count(token: str) -> int:
    settings = get_settings()
    if settings.shard_count > 0:
        return settings.shard_count
    async with aiohttp.ClientSession() as session:
        async with session.get(GATEWAY_URL, headers={"Authorization": f"Bot {token}"}) as response:
            data = await response.json(content_type=None)
            if response.status != 200:
                raise RuntimeError(f"Discord gateway lookup failed ({response.status}): {data}")
    return max(1, int(data.get("shards") or 1))


async def claim_shards(node_id: str, shard_count: int) -> list[int]:
    hostname = socket.gethostname()
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO cluster_nodes (node_id, hostname, last_seen, claimed_shards)
                VALUES (:node, :hostname, now(), '[]'::jsonb)
                ON CONFLICT (node_id) DO UPDATE
                SET hostname = EXCLUDED.hostname, last_seen = now()
                """
            ),
            {"node": node_id, "hostname": hostname},
        )
        await session.execute(
            text(
                """
                INSERT INTO shard_leases (shard_id, node_id, leased_until)
                SELECT gs, NULL, now()
                FROM generate_series(0, :max_shard) AS gs
                ON CONFLICT (shard_id) DO NOTHING
                """
            ),
            {"max_shard": shard_count - 1},
        )
        holders = await session.scalar(
            text(
                """
                SELECT count(DISTINCT node_id)
                FROM shard_leases
                WHERE leased_until > now()
                  AND node_id IS NOT NULL
                  AND node_id <> :node
                """
            ),
            {"node": node_id},
        )
        slots = int(holders or 0) + 1
        quota = max(1, math.ceil(shard_count / slots))
        await session.execute(
            text(
                """
                UPDATE shard_leases
                SET leased_until = now() + interval '15 seconds'
                WHERE node_id = :node AND leased_until > now()
                """
            ),
            {"node": node_id},
        )
        await session.execute(
            text(
                """
                WITH need AS (
                    SELECT GREATEST(
                        :quota - (
                            SELECT count(*) FROM shard_leases
                            WHERE node_id = :node AND leased_until > now()
                        ),
                        0
                    ) AS n
                ),
                claimable AS (
                    SELECT shard_id
                    FROM shard_leases
                    WHERE node_id IS NULL OR leased_until <= now()
                    ORDER BY shard_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT (SELECT n FROM need)
                )
                UPDATE shard_leases AS lease
                SET node_id = :node,
                    leased_until = now() + interval '15 seconds'
                FROM claimable
                WHERE lease.shard_id = claimable.shard_id
                """
            ),
            {"node": node_id, "quota": quota},
        )
        rows = await session.execute(
            text(
                """
                SELECT shard_id FROM shard_leases
                WHERE node_id = :node AND leased_until > now()
                ORDER BY shard_id
                """
            ),
            {"node": node_id},
        )
        shard_ids = [int(row[0]) for row in rows]
        await session.execute(
            text(
                """
                UPDATE cluster_nodes
                SET claimed_shards = CAST(:shards AS jsonb), last_seen = now()
                WHERE node_id = :node
                """
            ),
            {"node": node_id, "shards": json.dumps(shard_ids)},
        )
        await session.commit()
        log.info("node %s holds shards %s (quota %s)", node_id, shard_ids, quota)
        return shard_ids


async def renew_leases(node_id: str, shard_ids: list[int]) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                UPDATE shard_leases
                SET leased_until = now() + interval '15 seconds'
                WHERE node_id = :node
                """
            ),
            {"node": node_id},
        )
        await session.execute(
            text(
                """
                UPDATE cluster_nodes
                SET last_seen = now(), claimed_shards = CAST(:shards AS jsonb)
                WHERE node_id = :node
                """
            ),
            {"node": node_id, "shards": json.dumps(shard_ids)},
        )
        await session.commit()


async def release_leases(node_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                UPDATE shard_leases
                SET node_id = NULL, leased_until = now()
                WHERE node_id = :node
                """
            ),
            {"node": node_id},
        )
        await session.execute(
            text(
                """
                UPDATE cluster_nodes
                SET claimed_shards = '[]'::jsonb, last_seen = now()
                WHERE node_id = :node
                """
            ),
            {"node": node_id},
        )
        await session.commit()
        log.info("released shard leases for %s", node_id)


async def heartbeat_loop(node_id: str, shard_ids: list[int]) -> None:
    try:
        while True:
            try:
                await renew_leases(node_id, shard_ids)
            except Exception:
                log.exception("shard heartbeat failed")
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        return


async def listen_forever() -> None:
    import asyncpg

    from bot.cache import get_cache

    dsn = asyncpg_dsn()
    while True:
        conn = None
        try:
            conn = await asyncpg.connect(dsn)

            def _on_notify(_conn, _pid, _channel, payload: str) -> None:
                guild_id = int(payload) if payload else None
                get_cache().invalidate(guild_id)
                log.info("invalidated guild cache %s", payload or "*")

            await conn.add_listener("guild_invalidate", _on_notify)
            while not conn.is_closed():
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            if conn is not None and not conn.is_closed():
                await conn.close()
            raise
        except Exception:
            log.exception("guild invalidation listener dropped")
            await asyncio.sleep(2)
        finally:
            if conn is not None and not conn.is_closed():
                await conn.close()
