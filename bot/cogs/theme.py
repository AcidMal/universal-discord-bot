from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.cache import get_cache
from bot.cogs.common import prepare
from shared.db import get_session_factory
from shared.enums import AuditSource
from shared.models import GuildTheme
from shared.services import add_audit, apply_preset, ensure_guild, notify_guild
from shared.theme import PRESETS, render_embed


class Theme(commands.Cog):
    theme = app_commands.Group(name="theme", description="Preview or apply the server look")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @theme.command(name="preview", description="Preview the current case embed")
    @app_commands.guild_only()
    async def preview(self, interaction: discord.Interaction) -> None:
        if not await prepare(interaction, "theme"):
            return
        assert interaction.guild is not None
        state = await get_cache().get(interaction.guild.id)
        embed = discord.Embed.from_dict(
            render_embed(
                state.theme,
                "case",
                {
                    "case": "42",
                    "type": "warn",
                    "target": interaction.user.mention,
                    "reason": "This is a preview. Nothing was saved.",
                    "moderator": interaction.user.mention,
                },
            )
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @theme.command(name="preset", description="Apply a built-in look")
    @app_commands.describe(preset="Midnight, Light, Nord, or Rose")
    @app_commands.choices(
        preset=[
            app_commands.Choice(name="Midnight", value="midnight"),
            app_commands.Choice(name="Light", value="light"),
            app_commands.Choice(name="Nord", value="nord"),
            app_commands.Choice(name="Rose", value="rose"),
        ]
    )
    @app_commands.guild_only()
    async def apply(
        self,
        interaction: discord.Interaction,
        preset: app_commands.Choice[str],
    ) -> None:
        if not await prepare(interaction, "theme"):
            return
        assert interaction.guild is not None
        if preset.value not in PRESETS:
            await interaction.response.send_message("Unknown preset.", ephemeral=True)
            return
        factory = get_session_factory()
        async with factory() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            theme = await session.get(GuildTheme, interaction.guild.id)
            if theme is None:
                await interaction.response.send_message("Theme row is missing.", ephemeral=True)
                return
            apply_preset(theme, preset.value)
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action="theme.preset",
                source=AuditSource.COMMAND,
                payload={"preset": preset.value},
            )
            await notify_guild(session, interaction.guild.id)
            await session.commit()
        get_cache().invalidate(interaction.guild.id)
        await interaction.response.send_message(f"Applied the {preset.name} look.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Theme(bot))
