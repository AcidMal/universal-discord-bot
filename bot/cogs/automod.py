from __future__ import annotations

import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.automod_engine import handle_message
from bot.cache import get_cache
from bot.cogs.common import prepare
from bot.duration import parse_duration
from shared.automod import describe_rule, normalize_config
from shared.db import get_session_factory
from shared.enums import AuditSource
from shared.models import AutomodRule
from shared.services import add_audit, notify_guild

ACTIONS = [
    app_commands.Choice(name="Delete the message", value="delete"),
    app_commands.Choice(name="Warn", value="warn"),
    app_commands.Choice(name="Timeout", value="timeout"),
    app_commands.Choice(name="Kick", value="kick"),
    app_commands.Choice(name="Ban", value="ban"),
]
RAID_ACTIONS = [
    app_commands.Choice(name="Warn", value="warn"),
    app_commands.Choice(name="Timeout", value="timeout"),
    app_commands.Choice(name="Kick", value="kick"),
    app_commands.Choice(name="Ban", value="ban"),
]


def _chosen(action: app_commands.Choice[str] | None, default: str) -> str:
    return action.value if action is not None else default


def _timeout_seconds(action: str, duration: str | None) -> int | None:
    if action != "timeout":
        return None
    if duration is None or not duration.strip():
        return 600
    return parse_duration(duration)


class Automod(commands.Cog):
    automod = app_commands.Group(name="automod", description="Create and manage automod rules")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await handle_message(self.bot, message)

    def _match(self, rows: list[AutomodRule], raw: str) -> AutomodRule | None:
        needle = raw.strip().lower()
        try:
            wanted = uuid.UUID(needle)
        except ValueError:
            wanted = None
        if wanted is not None:
            return next((row for row in rows if row.id == wanted), None)
        matches = [row for row in rows if str(row.id).startswith(needle) or row.name.lower() == needle]
        if len(matches) == 1:
            return matches[0]
        return None

    async def _create(
        self,
        interaction: discord.Interaction,
        *,
        name: str,
        rule_type: str,
        action: str,
        config: dict[str, Any],
    ) -> None:
        assert interaction.guild is not None
        label = name.strip()
        if not label:
            await interaction.response.send_message("Give the rule a name.", ephemeral=True)
            return
        try:
            cleaned = normalize_config(rule_type, action, config)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        factory = get_session_factory()
        async with factory() as session:
            row = AutomodRule(
                guild_id=interaction.guild.id,
                name=label[:100],
                type=rule_type,
                action=action,
                enabled=True,
                config=cleaned,
            )
            session.add(row)
            await session.flush()
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action="automod.create",
                source=AuditSource.COMMAND,
                target_type="automod_rule",
                target_id=str(row.id),
            )
            await notify_guild(session, interaction.guild.id)
            await session.commit()
        get_cache().invalidate(interaction.guild.id)
        summary = describe_rule(rule_type, action, cleaned)
        await interaction.response.send_message(f"Added **{label}**. {summary}", ephemeral=True)

    @automod.command(name="words", description="Block messages that contain these words")
    @app_commands.describe(
        name="Name shown in the rule list",
        words="Words separated by commas",
        action="What happens on a match. Defaults to deleting the message",
        whole_word="Match the whole word only",
        duration="Timeout length, such as 10m. Used when the action is timeout",
    )
    @app_commands.choices(action=ACTIONS)
    @app_commands.guild_only()
    async def words(
        self,
        interaction: discord.Interaction,
        name: str,
        words: str,
        action: app_commands.Choice[str] | None = None,
        whole_word: bool = True,
        duration: str | None = None,
    ) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        chosen = _chosen(action, "delete")
        try:
            timeout = _timeout_seconds(chosen, duration)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        config: dict[str, Any] = {"words": words, "whole_word": whole_word}
        if timeout is not None:
            config["timeout_seconds"] = timeout
        await self._create(interaction, name=name, rule_type="words", action=chosen, config=config)

    @automod.command(name="links", description="Block links, except domains you allow")
    @app_commands.describe(
        name="Name shown in the rule list",
        allow="Domains to leave alone, separated by commas. Empty blocks every link",
        action="What happens on a match. Defaults to deleting the message",
        duration="Timeout length, such as 10m. Used when the action is timeout",
    )
    @app_commands.choices(action=ACTIONS)
    @app_commands.guild_only()
    async def links(
        self,
        interaction: discord.Interaction,
        name: str,
        allow: str | None = None,
        action: app_commands.Choice[str] | None = None,
        duration: str | None = None,
    ) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        chosen = _chosen(action, "delete")
        try:
            timeout = _timeout_seconds(chosen, duration)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        config: dict[str, Any] = {"allow_domains": allow or ""}
        if timeout is not None:
            config["timeout_seconds"] = timeout
        await self._create(interaction, name=name, rule_type="links", action=chosen, config=config)

    @automod.command(name="mentions", description="Limit how many mentions one message can have")
    @app_commands.describe(
        name="Name shown in the rule list",
        limit="Mentions allowed before the rule fires",
        action="What happens on a match. Defaults to deleting the message",
        duration="Timeout length, such as 10m. Used when the action is timeout",
    )
    @app_commands.choices(action=ACTIONS)
    @app_commands.guild_only()
    async def mentions(
        self,
        interaction: discord.Interaction,
        name: str,
        limit: app_commands.Range[int, 1, 25] = 5,
        action: app_commands.Choice[str] | None = None,
        duration: str | None = None,
    ) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        chosen = _chosen(action, "delete")
        try:
            timeout = _timeout_seconds(chosen, duration)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        config: dict[str, Any] = {"max_mentions": limit}
        if timeout is not None:
            config["timeout_seconds"] = timeout
        await self._create(interaction, name=name, rule_type="mentions", action=chosen, config=config)

    @automod.command(name="spam", description="Limit how fast one person can send messages")
    @app_commands.describe(
        name="Name shown in the rule list",
        messages="Messages allowed inside the time window",
        window="Time window, such as 7 or 10s",
        action="What happens on a match. Defaults to a 10 minute timeout",
        duration="Timeout length, such as 10m. Used when the action is timeout",
    )
    @app_commands.choices(action=ACTIONS)
    @app_commands.guild_only()
    async def spam(
        self,
        interaction: discord.Interaction,
        name: str,
        messages: app_commands.Range[int, 2, 30] = 5,
        window: str = "7",
        action: app_commands.Choice[str] | None = None,
        duration: str | None = None,
    ) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        chosen = _chosen(action, "timeout")
        try:
            seconds = parse_duration(window, bare_unit="s")
            timeout = _timeout_seconds(chosen, duration)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        config: dict[str, Any] = {"max_messages": messages, "window_seconds": seconds}
        if timeout is not None:
            config["timeout_seconds"] = timeout
        await self._create(interaction, name=name, rule_type="spam", action=chosen, config=config)

    @automod.command(name="raid", description="Punish a burst of new joins")
    @app_commands.describe(
        name="Name shown in the rule list",
        joins="Joins allowed inside the time window",
        window="Time window, such as 10 or 30s",
        action="What happens on a match. Defaults to kick",
        duration="Timeout length, such as 10m. Used when the action is timeout",
    )
    @app_commands.choices(action=RAID_ACTIONS)
    @app_commands.guild_only()
    async def raid(
        self,
        interaction: discord.Interaction,
        name: str,
        joins: app_commands.Range[int, 2, 50] = 8,
        window: str = "10",
        action: app_commands.Choice[str] | None = None,
        duration: str | None = None,
    ) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        chosen = _chosen(action, "kick")
        try:
            seconds = parse_duration(window, bare_unit="s")
            timeout = _timeout_seconds(chosen, duration)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        config: dict[str, Any] = {"max_joins": joins, "window_seconds": seconds}
        if timeout is not None:
            config["timeout_seconds"] = timeout
        await self._create(interaction, name=name, rule_type="raid", action=chosen, config=config)

    @automod.command(name="list", description="List automod rules")
    @app_commands.guild_only()
    async def list_rules(self, interaction: discord.Interaction) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AutomodRule)
                        .where(AutomodRule.guild_id == interaction.guild.id)
                        .order_by(AutomodRule.created_at)
                    )
                ).all()
            )
            lines = []
            for row in rows:
                state = "on" if row.enabled else "off"
                summary = describe_rule(row.type, row.action, dict(row.config or {}))
                lines.append(f"**{row.name}** · {state}\n{summary}\n`{str(row.id)[:8]}`")
        if not lines:
            await interaction.response.send_message(
                "No automod rules yet. Try `/automod words`, `/automod links`, `/automod mentions`, `/automod spam`, or `/automod raid`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message("\n\n".join(lines)[:1900], ephemeral=True)

    @automod.command(name="toggle", description="Enable or disable an automod rule")
    @app_commands.describe(rule="Rule name, or the first characters of its id")
    @app_commands.guild_only()
    async def toggle_rule(self, interaction: discord.Interaction, rule: str) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            rows = list(
                (
                    await session.scalars(select(AutomodRule).where(AutomodRule.guild_id == interaction.guild.id))
                ).all()
            )
            chosen = self._match(rows, rule)
            if chosen is None:
                await interaction.response.send_message(
                    "No single rule matched that name. Use `/automod list` and try the id.",
                    ephemeral=True,
                )
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
            f"**{label}** is now {'on' if enabled else 'off'}.",
            ephemeral=True,
        )

    @automod.command(name="remove", description="Delete an automod rule")
    @app_commands.describe(rule="Rule name, or the first characters of its id")
    @app_commands.guild_only()
    async def remove_rule(self, interaction: discord.Interaction, rule: str) -> None:
        if not await prepare(interaction, "automod", "automod"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            rows = list(
                (
                    await session.scalars(select(AutomodRule).where(AutomodRule.guild_id == interaction.guild.id))
                ).all()
            )
            chosen = self._match(rows, rule)
            if chosen is None:
                await interaction.response.send_message(
                    "No single rule matched that name. Use `/automod list` and try the id.",
                    ephemeral=True,
                )
                return
            label = chosen.name or chosen.type
            await session.delete(chosen)
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action="automod.delete",
                source=AuditSource.COMMAND,
                target_type="automod_rule",
                target_id=str(chosen.id),
            )
            await notify_guild(session, interaction.guild.id)
            await session.commit()
        get_cache().invalidate(interaction.guild.id)
        await interaction.response.send_message(f"Removed **{label}**.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Automod(bot))
