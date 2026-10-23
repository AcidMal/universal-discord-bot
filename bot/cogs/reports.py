from __future__ import annotations

import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from bot.actions import send_themed
from bot.cache import get_cache
from bot.cogs.common import prepare
from shared.db import get_session_factory
from shared.enums import AuditSource, ReportStatus
from shared.models import Report
from shared.services import add_audit, ensure_guild, find_report_match, notify_guild, reports_for_guild

JUMP_RE = re.compile(r"channels/(\d+)/(\d+)/(\d+)")


class Reports(commands.Cog):
    reports = app_commands.Group(name="reports", description="Staff queue for member reports")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="report", description="Report a member to the staff team")
    @app_commands.describe(
        member="Member you are reporting",
        reason="What happened",
        message_link="Optional message jump link",
    )
    @app_commands.guild_only()
    async def report(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        message_link: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        factory = get_session_factory()
        async with factory() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            await session.commit()
        state = await get_cache().get(interaction.guild.id)
        if not state.module_toggles.get("reports", True):
            await interaction.response.send_message("Reports are turned off in this server.", ephemeral=True)
            return
        if member.id == interaction.user.id:
            await interaction.response.send_message("You can't report yourself.", ephemeral=True)
            return
        channel_id = None
        message_id = None
        if message_link:
            matched = JUMP_RE.search(message_link)
            if matched is None or int(matched.group(1)) != interaction.guild.id:
                await interaction.response.send_message(
                    "That message link is not from this server.",
                    ephemeral=True,
                )
                return
            channel_id = int(matched.group(2))
            message_id = int(matched.group(3))
        body = reason.strip() or "No details provided."
        async with factory() as session:
            row = Report(
                guild_id=interaction.guild.id,
                reporter_id=interaction.user.id,
                target_id=member.id,
                channel_id=channel_id,
                message_id=message_id,
                jump_url=message_link,
                reason=body[:2000],
                status=ReportStatus.OPEN,
            )
            session.add(row)
            await session.flush()
            report_id = row.id
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action="report.open",
                source=AuditSource.COMMAND,
                target_type="user",
                target_id=str(member.id),
                payload={"report_id": str(report_id)},
            )
            await session.commit()
        await send_themed(
            self.bot,
            theme=state.theme,
            template_key="report",
            substitutions={
                "case": str(report_id)[:8],
                "type": "report",
                "target": member.mention,
                "reason": body,
                "moderator": interaction.user.mention,
            },
            channel_id=state.log_channel_id,
        )
        await interaction.response.send_message(
            f"Report `{str(report_id)[:8]}` sent to staff.",
            ephemeral=True,
        )

    async def _set_status(self, interaction: discord.Interaction, report_id: str, status: str) -> None:
        if not await prepare(interaction, "reports_staff", "reports"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            rows = await reports_for_guild(session, interaction.guild.id, limit=200)
            row = find_report_match(rows, report_id)
            if row is None:
                await interaction.response.send_message("No report matched that id.", ephemeral=True)
                return
            row.status = status
            if status == ReportStatus.CLAIMED:
                row.claimed_by = interaction.user.id
            if status in {ReportStatus.RESOLVED, ReportStatus.REJECTED}:
                row.resolved_at = datetime.now(timezone.utc)
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action=f"report.{status}",
                source=AuditSource.COMMAND,
                target_type="report",
                target_id=str(row.id),
            )
            await notify_guild(session, interaction.guild.id)
            await session.commit()
            label = str(row.id)[:8]
        await interaction.response.send_message(f"Report `{label}` is now `{status}`.", ephemeral=True)

    @reports.command(name="list", description="List open reports")
    @app_commands.guild_only()
    async def list_reports(self, interaction: discord.Interaction) -> None:
        if not await prepare(interaction, "reports_staff", "reports"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            rows = await reports_for_guild(session, interaction.guild.id, status=ReportStatus.OPEN, limit=15)
            claimed = await reports_for_guild(session, interaction.guild.id, status=ReportStatus.CLAIMED, limit=15)
            lines = [
                f"`{str(row.id)[:8]}` {row.status} <@{row.target_id}> by <@{row.reporter_id}> — {row.reason[:80]}"
                for row in rows + claimed
            ]
        if not lines:
            await interaction.response.send_message("The report queue is empty.", ephemeral=True)
            return
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    @reports.command(name="claim", description="Claim a report")
    @app_commands.describe(report_id="Report id or the first characters of it")
    @app_commands.guild_only()
    async def claim_report(self, interaction: discord.Interaction, report_id: str) -> None:
        await self._set_status(interaction, report_id, ReportStatus.CLAIMED)

    @reports.command(name="resolve", description="Resolve a report")
    @app_commands.describe(report_id="Report id or the first characters of it")
    @app_commands.guild_only()
    async def resolve_report(self, interaction: discord.Interaction, report_id: str) -> None:
        await self._set_status(interaction, report_id, ReportStatus.RESOLVED)

    @reports.command(name="reject", description="Reject a report")
    @app_commands.describe(report_id="Report id or the first characters of it")
    @app_commands.guild_only()
    async def reject_report(self, interaction: discord.Interaction, report_id: str) -> None:
        await self._set_status(interaction, report_id, ReportStatus.REJECTED)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reports(bot))
