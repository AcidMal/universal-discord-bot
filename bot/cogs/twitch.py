from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import func, select, text

from bot.cogs.common import prepare
from shared.db import get_engine, get_session_factory
from shared.models import TwitchAlert
from shared.services import ensure_guild
from shared.twitch import (
    TwitchError,
    delete_eventsub,
    ensure_eventsub,
    lookup_user,
    poll_live_channels,
    twitch_configured,
)
from shared.twitch_format import normalize_login
from sqlalchemy.dialects.postgresql import insert as pg_insert

log = logging.getLogger("bot.twitch")


class Twitch(commands.Cog):
    twitch = app_commands.Group(name="twitch", description="Notify a channel when a Twitch stream goes live")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.checker.start()

    def cog_unload(self) -> None:
        self.checker.cancel()

    @tasks.loop(seconds=10)
    async def checker(self) -> None:
        engine = get_engine()
        async with engine.connect() as connection:
            locked = await connection.scalar(text("SELECT pg_try_advisory_lock(42424201)"))
            await connection.commit()
            if not locked:
                return
            try:
                await poll_live_channels()
            except Exception:
                log.exception("twitch live check failed")
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(42424201)"))
                await connection.commit()

    @checker.before_loop
    async def before_checker(self) -> None:
        await self.bot.wait_until_ready()

    @twitch.command(name="add", description="Post an embed when a Twitch channel goes live")
    @app_commands.describe(channel="Discord channel for the alert", user="Twitch login or twitch.tv link")
    @app_commands.guild_only()
    async def add_alert(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        user: str,
    ) -> None:
        if not await prepare(interaction, "twitch"):
            return
        if not twitch_configured():
            await interaction.response.send_message(
                "Twitch is not configured. Set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET, then restart.",
                ephemeral=True,
            )
            return
        try:
            login = normalize_login(user)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            profile = await lookup_user(login)
        except TwitchError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            stmt = pg_insert(TwitchAlert).values(
                guild_id=interaction.guild.id,
                discord_channel_id=channel.id,
                twitch_login=profile["login"],
                twitch_user_id=profile["id"],
                enabled=True,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["guild_id", "twitch_user_id"],
                set_={
                    "discord_channel_id": stmt.excluded.discord_channel_id,
                    "twitch_login": stmt.excluded.twitch_login,
                    "enabled": True,
                },
            )
            await session.execute(stmt)
            await session.commit()
        note = await ensure_eventsub(profile["id"])
        message = f"When `{profile['login']}` goes live, an embed is posted in {channel.mention}."
        if note:
            message = f"{message}\n{note}"
        else:
            message = f"{message}\nTwitch will push the alert as soon as the stream starts."
        await interaction.followup.send(message, ephemeral=True)

    @twitch.command(name="remove", description="Stop live alerts for a Twitch channel")
    @app_commands.describe(user="Twitch login to remove")
    @app_commands.guild_only()
    async def remove_alert(self, interaction: discord.Interaction, user: str) -> None:
        if not await prepare(interaction, "twitch"):
            return
        try:
            login = normalize_login(user)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            row = await session.scalar(
                select(TwitchAlert).where(
                    TwitchAlert.guild_id == interaction.guild.id,
                    TwitchAlert.twitch_login == login,
                )
            )
            if row is None:
                await interaction.response.send_message(f"No alert for `{login}`.", ephemeral=True)
                return
            broadcaster_id = row.twitch_user_id
            await session.delete(row)
            await session.flush()
            remaining = await session.scalar(
                select(func.count()).select_from(TwitchAlert).where(TwitchAlert.twitch_user_id == broadcaster_id)
            )
            await session.commit()
        if not remaining and twitch_configured():
            await delete_eventsub(broadcaster_id)
        await interaction.response.send_message(f"Removed live alerts for `{login}`.", ephemeral=True)

    @twitch.command(name="list", description="Show Twitch live alerts in this server")
    @app_commands.guild_only()
    async def list_alerts(self, interaction: discord.Interaction) -> None:
        if not await prepare(interaction, "twitch"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(TwitchAlert)
                        .where(TwitchAlert.guild_id == interaction.guild.id)
                        .order_by(TwitchAlert.twitch_login)
                    )
                ).all()
            )
            lines = [f"`{row.twitch_login}` → <#{row.discord_channel_id}>" for row in rows]
        if not lines:
            await interaction.response.send_message("No Twitch alerts yet.", ephemeral=True)
            return
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Twitch(bot))
