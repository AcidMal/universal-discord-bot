"""Widen Twitch subscription status.

Twitch sends webhook_callback_verification_pending, which does not fit varchar(32).

Revision ID: 0005_twitch_status
Revises: 0004_status
Create Date: 2026-10-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_twitch_status"
down_revision: Union[str, Sequence[str], None] = "0004_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "twitch_subscriptions",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "twitch_subscriptions",
        "status",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
