"""Tickets, and a place to file them.

Revision ID: 0006_tickets
Revises: 0005_twitch_status
Create Date: 2026-10-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_tickets"
down_revision: Union[str, Sequence[str], None] = "0005_twitch_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("guild_config", sa.Column("ticket_category_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "guild_counters",
        sa.Column("next_ticket_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("opener_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("claimed_by", sa.BigInteger(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], name="fk_tickets_guild_id_guilds", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_tickets"),
        sa.UniqueConstraint("guild_id", "number", name="uq_tickets_guild_id_number"),
    )
    op.create_index("ix_tickets_guild_id_status", "tickets", ["guild_id", "status"])
    op.create_table(
        "ticket_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="fk_ticket_messages_ticket_id_tickets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ticket_messages"),
    )
    op.create_index(
        "ix_ticket_messages_ticket_id_created_at",
        "ticket_messages",
        ["ticket_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_messages_ticket_id_created_at", table_name="ticket_messages")
    op.drop_table("ticket_messages")
    op.drop_index("ix_tickets_guild_id_status", table_name="tickets")
    op.drop_table("tickets")
    op.drop_column("guild_counters", "next_ticket_number")
    op.drop_column("guild_config", "ticket_category_id")
