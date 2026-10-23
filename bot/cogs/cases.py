from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.access import hierarchy_problem
from bot.actions import open_case
from bot.cache import get_cache
from bot.cogs.common import prepare
from bot.duration import parse_duration
from shared.db import get_session_factory
from shared.enums import CaseType
from shared.models import Case
from shared.services import cases_for_guild


def _case_line(case: Case) -> str:
    when = case.created_at.strftime("%Y-%m-%d %H:%M UTC") if case.created_at else ""
    state = "reversed" if case.reversed_at else case.type
    return f"`#{case.case_number}` {state} <@{case.target_id}> — {case.reason[:80]} ({when})"


class Cases(commands.Cog):
    case = app_commands.Group(name="case", description="Look up moderation cases")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _punish(
        self,
        interaction: discord.Interaction,
        *,
        action: str,
        case_type: str,
        target: discord.Member | discord.User,
        reason: str,
        evidence: str | None,
        duration: str | None,
        schedule_action: str | None,
    ) -> None:
        if not await prepare(interaction, action, "cases"):
            return
        assert interaction.guild is not None and isinstance(interaction.user, discord.Member)
        if isinstance(target, discord.Member):
            problem = hierarchy_problem(interaction.user, target)
            if problem:
                await interaction.response.send_message(problem, ephemeral=True)
                return
        seconds = None
        if case_type == CaseType.TIMEOUT:
            state = await get_cache().get(interaction.guild.id)
            try:
                seconds = parse_duration(duration) if duration else state.timeout_default_seconds
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        elif duration:
            try:
                seconds = parse_duration(duration)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.defer(ephemeral=True)
        audit_reason = reason.strip() or "No reason provided."
        try:
            if case_type == CaseType.TIMEOUT and isinstance(target, discord.Member):
                await target.timeout(timedelta(seconds=seconds or 600), reason=audit_reason[:200])
            elif case_type == CaseType.KICK and isinstance(target, discord.Member):
                await target.kick(reason=audit_reason[:200])
            elif case_type == CaseType.BAN:
                await interaction.guild.ban(target, reason=audit_reason[:200], delete_message_seconds=0)
            elif case_type == CaseType.UNBAN:
                await interaction.guild.unban(target, reason=audit_reason[:200])
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Discord rejected that action: {exc}", ephemeral=True)
            return
        number = await open_case(
            self.bot,
            guild=interaction.guild,
            case_type=case_type,
            target_id=target.id,
            moderator_id=interaction.user.id,
            reason=audit_reason,
            evidence=evidence,
            duration_seconds=seconds if schedule_action else None,
            schedule_action=schedule_action,
        )
        await interaction.followup.send(f"Opened case `#{number}`.", ephemeral=True)

    @app_commands.command(name="warn", description="Warn a member and open a case")
    @app_commands.describe(member="Member to warn", reason="Why", evidence="Optional evidence URL")
    @app_commands.guild_only()
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        evidence: str | None = None,
    ) -> None:
        await self._punish(
            interaction,
            action="warn",
            case_type=CaseType.WARN,
            target=member,
            reason=reason,
            evidence=evidence,
            duration=None,
            schedule_action=None,
        )

    @app_commands.command(name="timeout", description="Timeout a member and open a case")
    @app_commands.describe(
        member="Member to timeout",
        reason="Why",
        duration="Length such as 10m, 2h, or 1d. Blank uses the server default.",
        evidence="Optional evidence URL",
    )
    @app_commands.guild_only()
    async def timeout_member(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        duration: str | None = None,
        evidence: str | None = None,
    ) -> None:
        await self._punish(
            interaction,
            action="timeout",
            case_type=CaseType.TIMEOUT,
            target=member,
            reason=reason,
            evidence=evidence,
            duration=duration,
            schedule_action="untimeout",
        )

    @app_commands.command(name="kick", description="Kick a member and open a case")
    @app_commands.describe(member="Member to kick", reason="Why", evidence="Optional evidence URL")
    @app_commands.guild_only()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        evidence: str | None = None,
    ) -> None:
        await self._punish(
            interaction,
            action="kick",
            case_type=CaseType.KICK,
            target=member,
            reason=reason,
            evidence=evidence,
            duration=None,
            schedule_action=None,
        )

    @app_commands.command(name="ban", description="Ban a member and open a case")
    @app_commands.describe(
        member="Member to ban",
        reason="Why",
        duration="Optional timed ban, such as 7d. Blank is permanent.",
        evidence="Optional evidence URL",
    )
    @app_commands.guild_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        duration: str | None = None,
        evidence: str | None = None,
    ) -> None:
        schedule = "unban" if duration else None
        await self._punish(
            interaction,
            action="ban",
            case_type=CaseType.BAN,
            target=member,
            reason=reason,
            evidence=evidence,
            duration=duration,
            schedule_action=schedule,
        )

    @app_commands.command(name="unban", description="Remove a ban and open a case")
    @app_commands.describe(user="User to unban", reason="Why")
    @app_commands.guild_only()
    async def unban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
    ) -> None:
        await self._punish(
            interaction,
            action="unban",
            case_type=CaseType.UNBAN,
            target=user,
            reason=reason,
            evidence=None,
            duration=None,
            schedule_action=None,
        )

    @case.command(name="view", description="Show one case")
    @app_commands.describe(number="Case number")
    @app_commands.guild_only()
    async def view_case(self, interaction: discord.Interaction, number: int) -> None:
        if not await prepare(interaction, "warn", "cases"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select

            match = await session.scalar(
                select(Case).where(Case.guild_id == interaction.guild.id, Case.case_number == number)
            )
            line = _case_line(match) if match is not None else None
        if line is None:
            await interaction.response.send_message(f"No case `#{number}`.", ephemeral=True)
            return
        await interaction.response.send_message(line, ephemeral=True)

    @case.command(name="search", description="List recent cases for a user")
    @app_commands.describe(user="User to look up")
    @app_commands.guild_only()
    async def search_case(self, interaction: discord.Interaction, user: discord.User) -> None:
        if not await prepare(interaction, "warn", "cases"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            rows = await cases_for_guild(session, interaction.guild.id, target_id=user.id, limit=10)
            body = "\n".join(_case_line(row) for row in rows)
        if not body:
            await interaction.response.send_message("No cases for that user.", ephemeral=True)
            return
        await interaction.response.send_message(body[:1900], ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Cases(bot))
