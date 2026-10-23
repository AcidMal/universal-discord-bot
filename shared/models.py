from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuidv7_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )


class ClusterNode(Base):
    __tablename__ = "cluster_nodes"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    claimed_shards: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    leases: Mapped[list[ShardLease]] = relationship(back_populates="node")


class ShardLease(Base):
    __tablename__ = "shard_leases"

    shard_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    node_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("cluster_nodes.node_id", ondelete="SET NULL"),
        nullable=True,
    )
    leased_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    node: Mapped[ClusterNode | None] = relationship(back_populates="leases")


class Guild(Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    config: Mapped[GuildConfig | None] = relationship(back_populates="guild")
    theme: Mapped[GuildTheme | None] = relationship(back_populates="guild")


class GuildConfig(Base):
    __tablename__ = "guild_config"

    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en-US")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timeout_default_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    mute_default_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    module_toggles: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text(
            '\'{"cases": true, "automod": true, "lockdown": true, "reports": true, "notes": true}\'::jsonb'
        ),
    )
    ignored_channel_ids: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    ignored_role_ids: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    guild: Mapped[Guild] = relationship(back_populates="config")


class GuildTheme(Base):
    __tablename__ = "guild_theme"

    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    accent: Mapped[str] = mapped_column(String(7), nullable=False, default="#7C5CFF")
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    footer: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    author_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    embed_templates: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    background: Mapped[str] = mapped_column(String(7), nullable=False, default="#0B0C10")
    surface: Mapped[str] = mapped_column(String(7), nullable=False, default="#15171E")
    text: Mapped[str] = mapped_column(String(7), nullable=False, default="#E8EAF0")
    radius: Mapped[str] = mapped_column(String(16), nullable=False, default="8px")
    preset: Mapped[str] = mapped_column(String(32), nullable=False, default="midnight")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    guild: Mapped[Guild] = relationship(back_populates="theme")


class StaffRole(Base):
    __tablename__ = "staff_roles"
    __table_args__ = (UniqueConstraint("guild_id", "role_id"),)

    id: Mapped[uuid.UUID] = uuidv7_pk()
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    can_warn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_timeout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_kick: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_ban: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class GuildCounter(Base):
    __tablename__ = "guild_counters"

    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    next_case_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("guild_id", "case_number"),
        Index("ix_cases_guild_id_target_id", "guild_id", "target_id"),
        Index("ix_cases_guild_id_case_number", "guild_id", "case_number"),
    )

    id: Mapped[uuid.UUID] = uuidv7_pk()
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_number: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moderator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    log_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class MemberNote(Base):
    __tablename__ = "member_notes"
    __table_args__ = (Index("ix_member_notes_guild_id_target_id", "guild_id", "target_id"),)

    id: Mapped[uuid.UUID] = uuidv7_pk()
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_guild_id_status", "guild_id", "status"),)

    id: Mapped[uuid.UUID] = uuidv7_pk()
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
    )
    reporter_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    jump_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    claimed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutomodRule(Base):
    __tablename__ = "automod_rules"
    __table_args__ = (Index("ix_automod_rules_guild_id_enabled", "guild_id", "enabled"),)

    id: Mapped[uuid.UUID] = uuidv7_pk()
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class ScheduledAction(Base):
    __tablename__ = "scheduled_actions"
    __table_args__ = (
        Index(
            "ix_scheduled_actions_due",
            "run_at",
            postgresql_where=text("done_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuidv7_pk()
    guild_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=True,
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_guild_id_created_at", "guild_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuidv7_pk()
    guild_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=True,
    )
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class AutomodWindow(Base):
    __tablename__ = "automod_windows"
    __table_args__ = (UniqueConstraint("guild_id", "window_key"),)

    id: Mapped[uuid.UUID] = uuidv7_pk()
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_key: Mapped[str] = mapped_column(String(128), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Lockdown(Base):
    __tablename__ = "lockdowns"

    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    moderator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
