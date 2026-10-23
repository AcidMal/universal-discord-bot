from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

import discord

from bot.app import create_bot
from bot.cluster import claim_shards, heartbeat_loop, listen_forever, recommended_shard_count, release_leases
from shared.db import dispose_engine
from shared.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("bot")


async def _wait_for_shards(node_id: str, shard_count: int) -> list[int]:
    waited = 0
    while True:
        shards = await claim_shards(node_id, shard_count)
        if shards:
            return shards
        if waited % 30 == 0:
            log.info("no free shard lease yet; another node is holding them")
        await asyncio.sleep(5)
        waited += 5


async def main() -> None:
    settings = get_settings()
    log.info("node_id=%s public_url=%s", settings.node_id, settings.public_url)
    if not settings.discord_token:
        log.warning("DISCORD_TOKEN is empty. The bot will stay idle until you set one and restart.")
        await asyncio.Event().wait()
        return

    listener = asyncio.create_task(listen_forever())
    try:
        shard_count = await recommended_shard_count(settings.discord_token)
        log.info("shard_count=%s", shard_count)
        while True:
            shard_ids = await _wait_for_shards(settings.node_id, shard_count)
            bot = create_bot(shard_ids=shard_ids, shard_count=shard_count)
            bot.cluster_node_id = settings.node_id
            heartbeat = asyncio.create_task(heartbeat_loop(settings.node_id, shard_ids))
            try:
                await bot.start(settings.discord_token)
            except discord.LoginFailure:
                log.error("Discord rejected DISCORD_TOKEN")
                return
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                if not bot.is_closed():
                    await bot.close()
                await release_leases(settings.node_id)
            log.warning("gateway closed; reclaiming shards in 5s")
            await asyncio.sleep(5)
    finally:
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener
        await dispose_engine()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
