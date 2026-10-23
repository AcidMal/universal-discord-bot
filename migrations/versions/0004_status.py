"""Node roles, shard gateway status, and bot presence.

Revision ID: 0004_status
Revises: 0003_twitch
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_status"
down_revision: Union[str, Sequence[str], None] = "0003_twitch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cluster_nodes",
        sa.Column("role", sa.String(length=16), server_default="gateway", nullable=False),
    )
    op.add_column(
        "shard_leases",
        sa.Column("gateway_status", sa.String(length=32), server_default="unknown", nullable=False),
    )
    op.add_column("shard_leases", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("shard_leases", sa.Column("gateway_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "bot_profile",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("presence", sa.String(length=16), nullable=False),
        sa.Column("activity_type", sa.String(length=16), nullable=False),
        sa.Column("status_text", sa.String(length=128), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bot_profile"),
    )
    op.execute(
        "INSERT INTO bot_profile (id, presence, activity_type, status_text) VALUES (1, 'online', 'custom', '')"
    )


def downgrade() -> None:
    op.drop_table("bot_profile")
    op.drop_column("shard_leases", "gateway_updated_at")
    op.drop_column("shard_leases", "latency_ms")
    op.drop_column("shard_leases", "gateway_status")
    op.drop_column("cluster_nodes", "role")
