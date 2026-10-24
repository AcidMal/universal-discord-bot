from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select, text

from bot.access import member_can, module_enabled
from bot.cache import get_cache
from bot.cogs.common import deny, prepare
from shared.db import get_session_factory
from shared.enums import AuditSource
from shared.models import GuildConfig, Ticket, TicketMessage
from shared.services import add_audit, allocate_ticket_number, ensure_guild

log = logging.getLogger("bot.tickets")
_OPEN_LIMIT = 3


class TicketSubject(discord.ui.Modal, title="Open a ticket"):
    subject = discord.ui.TextInput(
        label="What do you need?",
        style=discord.TextStyle.paragraph,
        max_length=200,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await open_ticket(interaction, str(self.subject.value))


class OpenTicket(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Open a ticket", style=discord.ButtonStyle.primary, custom_id="udb:ticket:open")
    async def open_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketSubject())


async def open_ticket(interaction: discord.Interaction, subject: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await deny(interaction, "Use this in a server.")
        return
    if not await prepare(interaction, "ticket_open", "tickets"):
        return
    subject = subject.strip()[:200]
    if not subject:
        await deny(interaction, "Write a short subject first.")
        return
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        await interaction.followup.send("I need the Manage Channels permission to open a ticket.", ephemeral=True)
        return
    factory = get_session_factory()
    async with factory() as session:
        open_count = (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM tickets
                    WHERE guild_id = :guild AND opener_id = :opener AND status <> 'closed'
                    """
                ),
                {"guild": guild.id, "opener": interaction.user.id},
            )
        ).scalar_one()
        if int(open_count) >= _OPEN_LIMIT:
            await interaction.followup.send("You already have 3 open tickets.", ephemeral=True)
            return
        config = await session.get(GuildConfig, guild.id)
        category_id = config.ticket_category_id if config else None
        number = await allocate_ticket_number(session, guild.id)
        ticket = Ticket(
            guild_id=guild.id,
            number=number,
            opener_id=interaction.user.id,
            subject=subject,
            status="open",
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id
        await session.commit()

    category = guild.get_channel(category_id) if category_id else None
    if category is not None and not isinstance(category, discord.CategoryChannel):
        category = None
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
        ),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        ),
    }
    state = await get_cache().get(guild.id)
    for staff in state.staff:
        role = guild.get_role(staff.role_id)
        if role is None:
            continue
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
        )
    try:
        channel = await guild.create_text_channel(
            name=f"ticket-{number}",
            category=category,
            overwrites=overwrites,
            topic=subject[:1024],
            reason=f"Ticket {number} opened by {interaction.user}",
        )
    except discord.HTTPException as exc:
        log.warning("ticket channel failed in %s: %s", guild.id, exc)
        async with factory() as session:
            row = await session.get(Ticket, ticket_id)
            if row is not None:
                await session.delete(row)
                await session.commit()
        await interaction.followup.send("I couldn't create the ticket channel.", ephemeral=True)
        return
    async with factory() as session:
        row = await session.get(Ticket, ticket_id)
        if row is not None:
            row.channel_id = channel.id
            await add_audit(
                session,
                guild_id=guild.id,
                actor_id=interaction.user.id,
                action="ticket.open",
                source=AuditSource.COMMAND,
                target_type="ticket",
                target_id=str(ticket_id),
            )
            await session.commit()
    await channel.send(
        f"{interaction.user.mention} opened ticket **{number}**.\n{subject}\n\nStaff can reply here. `/ticket close` closes it."
    )
    await interaction.followup.send(f"Ticket {number} is in {channel.mention}.", ephemeral=True)


class Tickets(commands.Cog):
    ticket = app_commands.Group(name="ticket", description="Private help channels")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.deliver.start()

    async def cog_load(self) -> None:
        self.bot.add_view(OpenTicket())

    def cog_unload(self) -> None:
        self.deliver.cancel()

    @ticket.command(name="panel", description="Post a button that opens a ticket")
    @app_commands.guild_only()
    async def panel(self, interaction: discord.Interaction) -> None:
        if not await prepare(interaction, "setup", "tickets"):
            return
        await interaction.response.send_message(
            "Need help? Open a ticket and a private channel will be created for you and the staff.",
            view=OpenTicket(),
        )

    @ticket.command(name="open", description="Open a private ticket channel")
    @app_commands.describe(subject="What you need help with")
    @app_commands.guild_only()
    async def open_command(self, interaction: discord.Interaction, subject: str) -> None:
        await open_ticket(interaction, subject)

    @ticket.command(name="close", description="Close the ticket in this channel")
    @app_commands.guild_only()
    async def close_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.channel is None:
            await deny(interaction, "Use this inside a ticket channel.")
            return
        factory = get_session_factory()
        async with factory() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            await session.commit()
        get_cache().invalidate(interaction.guild.id)
        state = await get_cache().get(interaction.guild.id)
        if not module_enabled(state, "tickets"):
            await deny(interaction, "The tickets module is turned off for this server.")
            return
        async with factory() as session:
            ticket = (
                await session.execute(
                    select(Ticket).where(
                        Ticket.guild_id == interaction.guild.id,
                        Ticket.channel_id == interaction.channel.id,
                        Ticket.status != "closed",
                    )
                )
            ).scalar_one_or_none()
            if ticket is None:
                await deny(interaction, "This channel is not an open ticket.")
                return
            is_opener = interaction.user.id == ticket.opener_id
            is_staff = isinstance(interaction.user, discord.Member) and member_can(interaction.user, "tickets", state)
            if not is_opener and not is_staff:
                await deny(interaction, "Only the person who opened this ticket, or staff, can close it.")
                return
            ticket.status = "closed"
            ticket.closed_at = datetime.now(timezone.utc)
            await add_audit(
                session,
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                action="ticket.close",
                source=AuditSource.COMMAND,
                target_type="ticket",
                target_id=str(ticket.id),
            )
            await session.commit()
        await interaction.response.send_message("Closing this ticket.")

    @tasks.loop(seconds=4)
    async def deliver(self) -> None:
        await self._deliver_messages()
        await self._close_channels()

    @deliver.before_loop
    async def before_deliver(self) -> None:
        await self.bot.wait_until_ready()

    async def _deliver_messages(self) -> None:
        factory = get_session_factory()
        for _ in range(5):
            async with factory() as session:
                row = (
                    await session.execute(
                        text(
                            """
                            WITH pending AS (
                                SELECT id
                                FROM ticket_messages
                                WHERE delivered_at IS NULL
                                ORDER BY created_at
                                FOR UPDATE SKIP LOCKED
                                LIMIT 1
                            )
                            UPDATE ticket_messages AS message
                            SET delivered_at = now()
                            FROM pending
                            WHERE message.id = pending.id
                            RETURNING message.id, message.ticket_id, message.author_id, message.body
                            """
                        )
                    )
                ).mappings().first()
                await session.commit()
            if row is None:
                return
            async with factory() as session:
                ticket = await session.get(Ticket, row["ticket_id"])
                channel_id = ticket.channel_id if ticket else None
            if channel_id is None:
                continue
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    await channel.send(f"<@{row['author_id']}>: {str(row['body'])[:1900]}")
            except discord.NotFound:
                log.info("ticket channel %s is already gone", channel_id)
            except discord.HTTPException as exc:
                log.warning("could not deliver ticket message %s", row["id"])
                if exc.status is not None and exc.status < 500:
                    continue
                async with factory() as session:
                    await session.execute(
                        text("UPDATE ticket_messages SET delivered_at = NULL WHERE id = :id"),
                        {"id": row["id"]},
                    )
                    await session.commit()

    async def _close_channels(self) -> None:
        factory = get_session_factory()
        for _ in range(5):
            async with factory() as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT id, channel_id
                            FROM tickets
                            WHERE status = 'closed'
                              AND channel_id IS NOT NULL
                              AND NOT EXISTS (
                                  SELECT 1 FROM ticket_messages
                                  WHERE ticket_id = tickets.id AND delivered_at IS NULL
                              )
                            ORDER BY closed_at
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                            """
                        )
                    )
                ).mappings().first()
                if row is None:
                    return
                channel_id = int(row["channel_id"])
                ticket_id = row["id"]
                await session.execute(
                    text("UPDATE tickets SET channel_id = NULL WHERE id = :id"),
                    {"id": ticket_id},
                )
                await session.commit()
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    await channel.delete(reason="Ticket closed")
            except discord.HTTPException:
                log.warning("could not delete ticket channel %s", channel_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
