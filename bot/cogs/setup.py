from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from bot.cache import get_cache
from bot.cogs.common import prepare
from shared.db import get_session_factory
from shared.enums import AuditSource
from shared.models import GuildConfig
from shared.services import add_audit, ensure_guild, notify_guild, upsert_staff_role


class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Set the mod log channel, a staff role, and the timezone")
    @app_commands.describe(
        log_channel="Channel for case embeds",
        staff_role="Role that can warn, timeout, kick, and ban",
        timezone="IANA timezone, such as Australia/Sydney",
    )
    @app_commands.guild_only()
    async def setup_guild(
        self,
        interaction: discord.Interaction,
        log_channel: discord.TextChannel,
        staff_role: discord.Role,
        timezone: str = "UTC",
    ) -> None:
        if not await prepare(interaction, "setup"):
            return
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            await interaction.response.send_message(
                "That timezone is not recognized. Use an IANA name like `UTC` or `Australia/Sydney`.",
                ephemeral=True,
            )
            return
        if staff_role.is_default():
            await interaction.response.send_message("Pick a role other than @everyone.", ephemeral=True)
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            config = await session.get(GuildConfig, interaction.guild.id)
            if config is None:
                await interaction.response.send_message("Could not create server config.", ephemeral=True)
                return
            config.log_channel_id = log_channel.id
            config.timezone = timezone
            await upsert_staff_role(session, interaction.guild.id, staff_role.id)
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action="setup",
                source=AuditSource.COMMAND,
                payload={"log_channel_id": log_channel.id, "staff_role_id": staff_role.id, "timezone": timezone},
            )
            await notify_guild(session, interaction.guild.id)
            await session.commit()
        get_cache().invalidate(interaction.guild.id)
        await interaction.response.send_message(
            f"Saved. Logs go to {log_channel.mention}, {staff_role.mention} is staff, timezone is `{timezone}`.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Setup(bot))
