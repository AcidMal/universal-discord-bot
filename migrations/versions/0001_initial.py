"""Initial schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cluster_nodes",
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "claimed_shards",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("node_id", name="pk_cluster_nodes"),
    )
    op.create_table(
        "shard_leases",
        sa.Column("shard_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["cluster_nodes.node_id"],
            name="fk_shard_leases_node_id_cluster_nodes",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("shard_id", name="pk_shard_leases"),
    )
    op.create_table(
        "guilds",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_guilds"),
    )
    op.create_table(
        "guild_config",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("log_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("timeout_default_seconds", sa.Integer(), nullable=False),
        sa.Column("mute_default_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "module_toggles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                '\'{"cases": true, "automod": true, "lockdown": true, "reports": true, "notes": true}\'::jsonb'
            ),
            nullable=False,
        ),
        sa.Column(
            "ignored_channel_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "ignored_role_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_guild_config_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", name="pk_guild_config"),
    )
    op.create_table(
        "guild_theme",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("accent", sa.String(length=7), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("footer", sa.String(length=2048), nullable=False),
        sa.Column("author_name", sa.String(length=256), nullable=False),
        sa.Column(
            "embed_templates",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("background", sa.String(length=7), nullable=False),
        sa.Column("surface", sa.String(length=7), nullable=False),
        sa.Column("text", sa.String(length=7), nullable=False),
        sa.Column("radius", sa.String(length=16), nullable=False),
        sa.Column("preset", sa.String(length=32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_guild_theme_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", name="pk_guild_theme"),
    )
    op.create_table(
        "staff_roles",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("can_warn", sa.Boolean(), nullable=False),
        sa.Column("can_timeout", sa.Boolean(), nullable=False),
        sa.Column("can_kick", sa.Boolean(), nullable=False),
        sa.Column("can_ban", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_staff_roles_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_roles"),
        sa.UniqueConstraint("guild_id", "role_id", name="uq_staff_roles_guild_id"),
    )
    op.create_table(
        "guild_counters",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("next_case_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_guild_counters_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", name="pk_guild_counters"),
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("case_number", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("moderator_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("log_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("log_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_cases_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cases"),
        sa.UniqueConstraint("guild_id", "case_number", name="uq_cases_guild_id"),
    )
    op.create_index("ix_cases_guild_id_case_number", "cases", ["guild_id", "case_number"])
    op.create_index("ix_cases_guild_id_target_id", "cases", ["guild_id", "target_id"])
    op.create_table(
        "member_notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_member_notes_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_member_notes"),
    )
    op.create_index(
        "ix_member_notes_guild_id_target_id",
        "member_notes",
        ["guild_id", "target_id"],
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("reporter_id", sa.BigInteger(), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("jump_url", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("claimed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_reports_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reports"),
    )
    op.create_index("ix_reports_guild_id_status", "reports", ["guild_id", "status"])
    op.create_table(
        "automod_rules",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_automod_rules_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_automod_rules"),
    )
    op.create_index(
        "ix_automod_rules_guild_id_enabled",
        "automod_rules",
        ["guild_id", "enabled"],
    )
    op.create_table(
        "scheduled_actions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=True),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(length=64), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name="fk_scheduled_actions_case_id_cases",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_scheduled_actions_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scheduled_actions"),
    )
    op.create_index(
        "ix_scheduled_actions_due",
        "scheduled_actions",
        ["run_at"],
        postgresql_where=sa.text("done_at IS NULL"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_audit_log_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index(
        "ix_audit_log_guild_id_created_at",
        "audit_log",
        ["guild_id", "created_at"],
    )
    op.create_table(
        "automod_windows",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("window_key", sa.String(length=128), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column(
            "window_start",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.id"],
            name="fk_automod_windows_guild_id_guilds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_automod_windows"),
        sa.UniqueConstraint("guild_id", "window_key", name="uq_automod_windows_guild_id"),
    )
    op.create_table(
        "processed_events",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processed_events"),
    )


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("automod_windows")
    op.drop_index("ix_audit_log_guild_id_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_scheduled_actions_due", table_name="scheduled_actions")
    op.drop_table("scheduled_actions")
    op.drop_index("ix_automod_rules_guild_id_enabled", table_name="automod_rules")
    op.drop_table("automod_rules")
    op.drop_index("ix_reports_guild_id_status", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_member_notes_guild_id_target_id", table_name="member_notes")
    op.drop_table("member_notes")
    op.drop_index("ix_cases_guild_id_target_id", table_name="cases")
    op.drop_index("ix_cases_guild_id_case_number", table_name="cases")
    op.drop_table("cases")
    op.drop_table("guild_counters")
    op.drop_table("staff_roles")
    op.drop_table("guild_theme")
    op.drop_table("guild_config")
    op.drop_table("guilds")
    op.drop_table("shard_leases")
    op.drop_table("cluster_nodes")
