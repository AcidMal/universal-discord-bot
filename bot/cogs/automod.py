from __future__ import annotations

import uuid

import discord
from discord import app_commands
from discord.ext import commands

from bot.automod_engine import handle_message
from bot.cache import get_cache
from bot.cogs.common import prepare
from shared.db import get_session_factory
from shared.enums import AuditSource
from shared.models import AutomodRule
from shared.services import add_audit, notify_guild


class Automod(commands.Cog):
    automod = app_commands.Group(name="automod", description="List or toggle automod rules")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await handle_message(self.bot, message)

    @automod.command(name="list", description="List automod rules")
    @app_commands.guild_only()
    async def list_rules(self, interaction: discord.Interaction) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select

            rows = list(
                (
                    await session.scalars(
                        select(AutomodRule)
                        .where(AutomodRule.guild_id == interaction.guild.id)
                        .order_by(AutomodRule.created_at)
                    )
                ).all()
            )
            lines = [
                f"`{str(row.id)[:8]}` {'on' if row.enabled else 'off'} {row.type}/{row.action} {row.name}"
                for row in rows
            ]
        if not lines:
            await interaction.response.send_message(
                "No automod rules yet. Add them in the dashboard.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    @automod.command(name="toggle", description="Enable or disable an automod rule")
    @app_commands.describe(rule_id="Rule id or the first characters of it")
    @app_commands.guild_only()
    async def toggle_rule(self, interaction: discord.Interaction, rule_id: str) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select

            rows = list(
                (
                    await session.scalars(
                        select(AutomodRule).where(AutomodRule.guild_id == interaction.guild.id)
                    )
                ).all()
            )
            raw = rule_id.strip().lower()
            chosen: AutomodRule | None = None
            try:
                wanted = uuid.UUID(raw)
            except ValueError:
                wanted = None
            if wanted is not None:
                chosen = next((row for row in rows if row.id == wanted), None)
            else:
                matches = [row for row in rows if str(row.id).startswith(raw) or row.name.lower() == raw]
                if len(matches) == 1:
                    chosen = matches[0]
            if chosen is None:
                await interaction.response.send_message("No rule matched that id.", ephemeral=True)
                return
            chosen.enabled = not chosen.enabled
            enabled = chosen.enabled
            label = chosen.name or chosen.type
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action="automod.toggle",
                source=AuditSource.COMMAND,
                target_type="automod_rule",
                target_id=str(chosen.id),
                payload={"enabled": enabled},
            )
            await notify_guild(session, interaction.guild.id)
            await session.commit()
        get_cache().invalidate(interaction.guild.id)
        await interaction.response.send_message(
            f"`{label}` is now {'on' if enabled else 'off'}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Automod(bot))
