"""Guild rows, case numbers, automod windows, and cache-bust notifications."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.enums import AuditSource
from shared.models import (
    AuditLog,
    AutomodRule,
    Case,
    Guild,
    GuildConfig,
    GuildCounter,
    GuildTheme,
    Lockdown,
    MemberNote,
    Report,
    ScheduledAction,
    StaffRole,
)
from shared.theme import DEFAULT_EMBED_TEMPLATES, PRESETS

DEFAULT_TOGGLES = {
    "cases": True,
    "automod": True,
    "lockdown": True,
    "reports": True,
    "notes": True,
}


async def notify_guild(session: AsyncSession, guild_id: int) -> None:
    await session.execute(
        text("SELECT pg_notify('guild_invalidate', :payload)"),
        {"payload": str(guild_id)},
    )


async def ensure_guild(session: AsyncSession, guild_id: int, name: str) -> None:
    guild = await session.get(Guild, guild_id)
    if guild is None:
        session.add(Guild(id=guild_id, name=name[:100]))
        await session.flush()
    else:
        guild.name = name[:100]
        guild.left_at = None

    if await session.get(GuildConfig, guild_id) is None:
        session.add(
            GuildConfig(
                guild_id=guild_id,
                locale="en-US",
                timezone="UTC",
                timeout_default_seconds=600,
                mute_default_seconds=600,
                module_toggles=dict(DEFAULT_TOGGLES),
                ignored_channel_ids=[],
                ignored_role_ids=[],
            )
        )
    if await session.get(GuildTheme, guild_id) is None:
        preset = PRESETS["midnight"]
        session.add(
            GuildTheme(
                guild_id=guild_id,
                accent=preset.accent,
                logo_url=None,
                footer=preset.footer,
                author_name=preset.author_name,
                embed_templates={k: dict(v) for k, v in DEFAULT_EMBED_TEMPLATES.items()},
                background=preset.background,
                surface=preset.surface,
                text=preset.text,
                radius=preset.radius,
                preset="midnight",
            )
        )
    if await session.get(GuildCounter, guild_id) is None:
        session.add(GuildCounter(guild_id=guild_id, next_case_number=1))


async def mark_guild_left(session: AsyncSession, guild_id: int) -> None:
    guild = await session.get(Guild, guild_id)
    if guild is not None:
        guild.left_at = datetime.now(timezone.utc)


async def allocate_case_number(session: AsyncSession, guild_id: int) -> int:
    result = await session.execute(
        text(
            """
            INSERT INTO guild_counters (guild_id, next_case_number)
            VALUES (:guild_id, 2)
            ON CONFLICT (guild_id) DO UPDATE
            SET next_case_number = guild_counters.next_case_number + 1
            RETURNING next_case_number - 1 AS case_number
            """
        ),
        {"guild_id": guild_id},
    )
    return int(result.scalar_one())


async def add_audit(
    session: AsyncSession,
    *,
    guild_id: int | None,
    actor_id: int | None,
    action: str,
    source: str = AuditSource.SYSTEM,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            guild_id=guild_id,
            actor_id=actor_id,
            action=action,
            source=source,
            target_type=target_type,
            target_id=target_id,
            payload=payload or {},
        )
    )


async def bump_window(session: AsyncSession, guild_id: int, window_key: str, seconds: int) -> int:
    result = await session.execute(
        text(
            """
            INSERT INTO automod_windows (guild_id, window_key, count, window_start, expires_at)
            VALUES (:guild_id, :window_key, 1, now(), now() + make_interval(secs => :seconds))
            ON CONFLICT (guild_id, window_key) DO UPDATE SET
                count = CASE
                    WHEN automod_windows.expires_at <= now() THEN 1
                    ELSE automod_windows.count + 1
                END,
                window_start = CASE
                    WHEN automod_windows.expires_at <= now() THEN now()
                    ELSE automod_windows.window_start
                END,
                expires_at = CASE
                    WHEN automod_windows.expires_at <= now()
                    THEN now() + make_interval(secs => :seconds)
                    ELSE automod_windows.expires_at
                END
            RETURNING count
            """
        ),
        {"guild_id": guild_id, "window_key": window_key, "seconds": max(1, seconds)},
    )
    return int(result.scalar_one())


async def claim_event(session: AsyncSession, event_id: str) -> bool:
    result = await session.execute(
        text(
            """
            INSERT INTO processed_events (id)
            VALUES (:id)
            ON CONFLICT DO NOTHING
            RETURNING id
            """
        ),
        {"id": event_id},
    )
    return result.first() is not None


async def upsert_staff_role(
    session: AsyncSession,
    guild_id: int,
    role_id: int,
    *,
    can_warn: bool = True,
    can_timeout: bool = True,
    can_kick: bool = True,
    can_ban: bool = True,
) -> None:
    stmt = pg_insert(StaffRole).values(
        guild_id=guild_id,
        role_id=role_id,
        can_warn=can_warn,
        can_timeout=can_timeout,
        can_kick=can_kick,
        can_ban=can_ban,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["guild_id", "role_id"],
        set_={
            "can_warn": stmt.excluded.can_warn,
            "can_timeout": stmt.excluded.can_timeout,
            "can_kick": stmt.excluded.can_kick,
            "can_ban": stmt.excluded.can_ban,
        },
    )
    await session.execute(stmt)


def apply_preset(theme: GuildTheme, preset_name: str) -> None:
    preset = PRESETS[preset_name]
    theme.preset = preset_name
    theme.accent = preset.accent
    theme.background = preset.background
    theme.surface = preset.surface
    theme.text = preset.text
    theme.radius = preset.radius
    if not theme.embed_templates:
        theme.embed_templates = {k: dict(v) for k, v in DEFAULT_EMBED_TEMPLATES.items()}


async def load_guild_bundle(session: AsyncSession, guild_id: int) -> dict[str, Any]:
    config = await session.get(GuildConfig, guild_id)
    theme = await session.get(GuildTheme, guild_id)
    rules = (
        await session.scalars(
            select(AutomodRule)
            .where(AutomodRule.guild_id == guild_id, AutomodRule.enabled.is_(True))
            .order_by(AutomodRule.created_at)
        )
    ).all()
    staff = (
        await session.scalars(select(StaffRole).where(StaffRole.guild_id == guild_id))
    ).all()
    lockdown = await session.get(Lockdown, guild_id)
    return {
        "config": config,
        "theme": theme,
        "rules": list(rules),
        "staff": list(staff),
        "lockdown": lockdown,
    }


async def cases_for_guild(
    session: AsyncSession,
    guild_id: int,
    *,
    target_id: int | None = None,
    limit: int = 50,
) -> list[Case]:
    stmt = select(Case).where(Case.guild_id == guild_id)
    if target_id is not None:
        stmt = stmt.where(Case.target_id == target_id)
    stmt = stmt.order_by(Case.case_number.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


async def notes_for_target(session: AsyncSession, guild_id: int, target_id: int) -> list[MemberNote]:
    stmt = (
        select(MemberNote)
        .where(MemberNote.guild_id == guild_id, MemberNote.target_id == target_id)
        .order_by(MemberNote.created_at.desc())
        .limit(25)
    )
    return list((await session.scalars(stmt)).all())


async def reports_for_guild(
    session: AsyncSession,
    guild_id: int,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[Report]:
    stmt = select(Report).where(Report.guild_id == guild_id)
    if status:
        stmt = stmt.where(Report.status == status)
    stmt = stmt.order_by(Report.created_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


def find_report_match(rows: list[Report], raw: str) -> Report | None:
    raw = raw.strip().lower()
    try:
        wanted = uuid.UUID(raw)
    except ValueError:
        wanted = None
    if wanted is not None:
        for row in rows:
            if row.id == wanted:
                return row
        return None
    matches = [row for row in rows if str(row.id).startswith(raw)]
    if len(matches) == 1:
        return matches[0]
    return None


def schedule_payload(user_id: int) -> dict[str, Any]:
    return {"user_id": user_id, "attempts": 0}


def new_scheduled_action(
    *,
    guild_id: int,
    case_id: uuid.UUID,
    action: str,
    run_at: datetime,
    user_id: int,
) -> ScheduledAction:
    return ScheduledAction(
        guild_id=guild_id,
        case_id=case_id,
        action=action,
        payload=schedule_payload(user_id),
        run_at=run_at,
    )
