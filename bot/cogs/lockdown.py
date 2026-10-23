from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.actions import lockdown_begin, lockdown_end
from bot.cogs.common import prepare
from bot.duration import parse_duration
from shared.db import get_session_factory
from shared.models import Lockdown


class LockdownCog(commands.Cog):
    lockdown = app_commands.Group(name="lockdown", description="Stop and restore messages in text channels")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @lockdown.command(name="on", description="Deny @everyone send messages")
    @app_commands.describe(
        reason="Why the server is locking down",
        channel="One channel. Leave empty to lock every text channel the bot can edit.",
        duration="Optional length such as 30m or 2h",
    )
    @app_commands.guild_only()
    async def lockdown_on(
        self,
        interaction: discord.Interaction,
        reason: str,
        channel: discord.TextChannel | None = None,
        duration: str | None = None,
    ) -> None:
        if not await prepare(interaction, "lockdown", "lockdown"):
            return
        assert interaction.guild is not None and isinstance(interaction.user, discord.Member)
        factory = get_session_factory()
        async with factory() as session:
            current = await session.get(Lockdown, interaction.guild.id)
            active = bool(current and current.active)
        if active:
            await interaction.response.send_message(
                "Lockdown is already on. Turn it off before starting another.",
                ephemeral=True,
            )
            return
        try:
            seconds = parse_duration(duration) if duration else None
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        targets = [channel] if channel is not None else list(interaction.guild.text_channels)
        if len(targets) > 100:
            await interaction.response.send_message(
                "That is more than 100 text channels. Pass a single channel instead.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            number = await lockdown_begin(
                self.bot,
                interaction.guild,
                interaction.user,
                reason,
                targets,
                seconds,
            )
        except Exception as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(f"Lockdown is on. Case `#{number}`.", ephemeral=True)

    @lockdown.command(name="off", description="Restore channel permissions from before lockdown")
    @app_commands.guild_only()
    async def lockdown_off(self, interaction: discord.Interaction) -> None:
        if not await prepare(interaction, "lockdown", "lockdown"):
            return
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True)
        restored = await lockdown_end(self.bot, interaction.guild, "Lockdown ended")
        if not restored:
            await interaction.followup.send("This server is not locked down.", ephemeral=True)
            return
        await interaction.followup.send("Lockdown is off. Previous overwrites were restored.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LockdownCog(bot))
