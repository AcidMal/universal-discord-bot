from __future__ import annotations

import logging
import math

import discord
from discord.ext import commands, tasks
from sqlalchemy import text

from bot.automod_engine import handle_join
from bot.cluster import report_shard_gateway
from bot.presence import apply_saved, bind
from shared.db import get_engine, get_session_factory
from shared.services import ensure_guild, mark_guild_left

log = logging.getLogger("bot.core")


def _shard_snapshot(shard: discord.Shard) -> tuple[str, int | None]:
    is_closed = getattr(shard, "is_closed", None)
    if callable(is_closed) and is_closed():
        return "disconnected", None
    latency = shard.latency
    if latency is None or not math.isfinite(latency):
        return "connecting", None
    return "ready", max(0, int(latency * 1000))


class Core(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bind(bot)
        self.gateway_report.start()

    def cog_unload(self) -> None:
        self.gateway_report.cancel()

    async def _report(self, shard_id: int, status: str, latency_ms: int | None) -> None:
        node_id = getattr(self.bot, "cluster_node_id", "")
        if not node_id:
            return
        try:
            await report_shard_gateway(node_id, shard_id, status, latency_ms)
        except Exception:
            log.exception("shard status report failed")

    @tasks.loop(seconds=5)
    async def gateway_report(self) -> None:
        for shard_id, shard in self.bot.shards.items():
            status, latency_ms = _shard_snapshot(shard)
            await self._report(shard_id, status, latency_ms)

    @gateway_report.before_loop
    async def before_gateway_report(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_shard_connect(self, shard_id: int) -> None:
        await self._report(shard_id, "connecting", None)

    @commands.Cog.listener()
    async def on_shard_ready(self, shard_id: int) -> None:
        shard = self.bot.get_shard(shard_id)
        status, latency_ms = _shard_snapshot(shard) if shard is not None else ("ready", None)
        await self._report(shard_id, status, latency_ms)

    @commands.Cog.listener()
    async def on_shard_resumed(self, shard_id: int) -> None:
        shard = self.bot.get_shard(shard_id)
        status, latency_ms = _shard_snapshot(shard) if shard is not None else ("ready", None)
        await self._report(shard_id, status, latency_ms)

    @commands.Cog.listener()
    async def on_shard_disconnect(self, shard_id: int) -> None:
        await self._report(shard_id, "disconnected", None)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        log.info("gateway ready as %s shards=%s", self.bot.user, self.bot.shard_ids)
        await apply_saved()
        factory = get_session_factory()
        async with factory() as session:
            for guild in self.bot.guilds:
                await ensure_guild(session, guild.id, guild.name)
            await session.commit()
        if getattr(self.bot, "_commands_synced", False):
            return
        engine = get_engine()
        async with engine.connect() as connection:
            locked = await connection.scalar(text("SELECT pg_try_advisory_lock(42042042)"))
            if not locked:
                log.info("another node is syncing slash commands")
                return
            try:
                synced = await self.bot.tree.sync()
                log.info("synced %s slash commands", len(synced))
                self.bot._commands_synced = True
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(42042042)"))
                await connection.commit()

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        factory = get_session_factory()
        async with factory() as session:
            await ensure_guild(session, guild.id, guild.name)
            await session.commit()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        factory = get_session_factory()
        async with factory() as session:
            await mark_guild_left(session, guild.id)
            await session.commit()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await handle_join(self.bot, member)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Core(bot))
