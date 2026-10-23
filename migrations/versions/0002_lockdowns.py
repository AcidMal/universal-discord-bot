"""Lockdown snapshots.

Revision ID: 0002_lockdowns
Revises: 0001_initial
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_lockdowns"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lockdowns",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("moderator_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name="fk_lockdowns_case_id_cases",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_lockdowns_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", name="pk_lockdowns"),
    )


def downgrade() -> None:
    op.drop_table("lockdowns")
