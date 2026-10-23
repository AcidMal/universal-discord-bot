from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.common import prepare
from shared.db import get_session_factory
from shared.enums import AuditSource
from shared.models import MemberNote
from shared.services import add_audit, ensure_guild, notes_for_target


class Notes(commands.Cog):
    notes = app_commands.Group(name="notes", description="Staff notes that are not punishments")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @notes.command(name="add", description="Add a staff note on a member")
    @app_commands.describe(member="Member the note is about", text="Note body")
    @app_commands.guild_only()
    async def add_note(self, interaction: discord.Interaction, member: discord.Member, text: str) -> None:
        if not await prepare(interaction, "notes", "notes"):
            return
        assert interaction.guild is not None
        body = text.strip()
        if not body:
            await interaction.response.send_message("Write a note first.", ephemeral=True)
            return
        factory = get_session_factory()
        async with factory() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            session.add(
                MemberNote(
                    guild_id=interaction.guild.id,
                    target_id=member.id,
                    author_id=interaction.user.id,
                    body=body[:2000],
                )
            )
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action="note.add",
                source=AuditSource.COMMAND,
                target_type="user",
                target_id=str(member.id),
            )
            await session.commit()
        await interaction.response.send_message(f"Note saved for {member.mention}.", ephemeral=True)

    @notes.command(name="list", description="List staff notes for a member")
    @app_commands.describe(member="Member to look up")
    @app_commands.guild_only()
    async def list_notes(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not await prepare(interaction, "notes", "notes"):
            return
        assert interaction.guild is not None
        factory = get_session_factory()
        async with factory() as session:
            rows = await notes_for_target(session, interaction.guild.id, member.id)
            lines = []
            for note in rows:
                stamp = note.created_at.strftime("%Y-%m-%d") if note.created_at else ""
                lines.append(f"`{str(note.id)[:8]}` {stamp} <@{note.author_id}>: {note.body[:180]}")
        if not lines:
            await interaction.response.send_message("No notes for that member.", ephemeral=True)
            return
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Notes(bot))
