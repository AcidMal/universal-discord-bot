from __future__ import annotations

import logging

import discord
from discord.ext import commands
from sqlalchemy import text

from bot.automod_engine import handle_join
from shared.db import get_engine, get_session_factory
from shared.services import ensure_guild, mark_guild_left

log = logging.getLogger("bot.core")


class Core(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        log.info("gateway ready as %s shards=%s", self.bot.user, self.bot.shard_ids)
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
