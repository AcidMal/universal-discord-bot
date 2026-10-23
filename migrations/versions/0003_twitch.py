"""Twitch live alerts.

Revision ID: 0003_twitch
Revises: 0002_lockdowns
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_twitch"
down_revision: Union[str, Sequence[str], None] = "0002_lockdowns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "twitch_alerts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("twitch_login", sa.String(length=25), nullable=False),
        sa.Column("twitch_user_id", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_twitch_alerts_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_twitch_alerts"),
        sa.UniqueConstraint("guild_id", "twitch_user_id", name="uq_twitch_alerts_guild_id"),
    )
    op.create_index("ix_twitch_alerts_twitch_user_id", "twitch_alerts", ["twitch_user_id"])
    op.create_table(
        "twitch_live_state",
        sa.Column("broadcaster_id", sa.String(length=32), nullable=False),
        sa.Column("live", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("broadcaster_id", name="pk_twitch_live_state"),
    )
    op.create_table(
        "twitch_subscriptions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("broadcaster_id", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("subscription_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_twitch_subscriptions"),
        sa.UniqueConstraint("broadcaster_id", "event_type", name="uq_twitch_subscriptions_broadcaster_id"),
    )


def downgrade() -> None:
    op.drop_table("twitch_subscriptions")
    op.drop_table("twitch_live_state")
    op.drop_index("ix_twitch_alerts_twitch_user_id", table_name="twitch_alerts")
    op.drop_table("twitch_alerts")
