from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from sqlalchemy import select

from bot.cache import get_cache
from shared.db import get_session_factory
from shared.enums import AuditSource, CaseType
from shared.models import Case, GuildConfig, Lockdown, ScheduledAction
from shared.services import add_audit, allocate_case_number, ensure_guild, new_scheduled_action
from shared.theme import render_embed

log = logging.getLogger("bot.actions")


def _reason_text(reason: str, evidence: str | None) -> str:
    text = reason.strip() or "No reason provided."
    if evidence:
        text = f"{text}\nEvidence: {evidence}"
    return text


async def send_themed(
    bot: discord.Client,
    *,
    theme,
    template_key: str,
    substitutions: dict[str, str],
    channel_id: int | None,
) -> None:
    await _publish_log(
        bot,
        case_id=None,
        theme=theme,
        template_key=template_key,
        substitutions=substitutions,
        channel_id=channel_id,
    )


async def _publish_log(
    bot: discord.Client,
    *,
    case_id: uuid.UUID | None,
    theme,
    template_key: str,
    substitutions: dict[str, str],
    channel_id: int | None,
    message_id: int | None = None,
) -> None:
    if channel_id is None:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            log.warning("log channel %s is not reachable", channel_id)
            return
    if not isinstance(channel, discord.abc.Messageable):
        return
    embed = discord.Embed.from_dict(render_embed(theme, template_key, substitutions))
    if message_id is not None and isinstance(channel, discord.abc.Messageable):
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed)
            return
        except discord.HTTPException:
            log.info("could not edit log message %s; sending a new one", message_id)
    message = await channel.send(embed=embed)
    if case_id is None:
        return
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(Case, case_id)
        if row is not None:
            row.log_channel_id = channel.id
            row.log_message_id = message.id
            await session.commit()


async def open_case(
    bot: discord.Client,
    *,
    guild: discord.Guild,
    case_type: str,
    target_id: int,
    moderator_id: int | None,
    reason: str,
    evidence: str | None = None,
    duration_seconds: int | None = None,
    schedule_action: str | None = None,
    source: str = AuditSource.COMMAND,
    template_key: str = "mod_log",
) -> int:
    expires_at = None
    if duration_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    factory = get_session_factory()
    async with factory() as session:
        await ensure_guild(session, guild.id, guild.name)
        config = await session.get(GuildConfig, guild.id)
        number = await allocate_case_number(session, guild.id)
        case = Case(
            guild_id=guild.id,
            case_number=number,
            type=case_type,
            target_id=target_id,
            moderator_id=moderator_id,
            reason=reason.strip() or "No reason provided.",
            evidence_url=evidence,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            log_channel_id=config.log_channel_id if config else None,
        )
        session.add(case)
        await session.flush()
        if schedule_action and expires_at is not None:
            session.add(
                new_scheduled_action(
                    guild_id=guild.id,
                    case_id=case.id,
                    action=schedule_action,
                    run_at=expires_at,
                    user_id=target_id,
                )
            )
        await add_audit(
            session,
            guild_id=guild.id,
            actor_id=moderator_id,
            action=f"case.{case_type}",
            source=source,
            target_type="user",
            target_id=str(target_id),
            payload={"case_number": number, "reason": case.reason},
        )
        await session.commit()
        case_id = case.id
        log_channel_id = case.log_channel_id
        stored_reason = case.reason
    get_cache().invalidate(guild.id)
    state = await get_cache().get(guild.id)
    substitutions = {
        "case": str(number),
        "type": case_type,
        "target": f"<@{target_id}>",
        "reason": _reason_text(stored_reason, evidence),
        "moderator": f"<@{moderator_id}>" if moderator_id else "Automod",
    }
    await _publish_log(
        bot,
        case_id=case_id,
        theme=state.theme,
        template_key=template_key,
        substitutions=substitutions,
        channel_id=log_channel_id,
    )
    return number


async def reverse_case(bot: discord.Client, case_id: uuid.UUID, note: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        case = await session.get(Case, case_id)
        if case is None or case.reversed_at is not None:
            return
        case.reversed_at = datetime.now(timezone.utc)
        channel_id = case.log_channel_id
        message_id = case.log_message_id
        guild_id = case.guild_id
        substitutions = {
            "case": str(case.case_number),
            "type": case.type,
            "target": f"<@{case.target_id}>",
            "reason": f"{case.reason}\n\nReversed: {note}",
            "moderator": f"<@{case.moderator_id}>" if case.moderator_id else "Automod",
        }
        await session.commit()
    state = await get_cache().get(guild_id)
    await _publish_log(
        bot,
        case_id=case_id,
        theme=state.theme,
        template_key="mod_log",
        substitutions=substitutions,
        channel_id=channel_id,
        message_id=message_id,
    )


async def lockdown_begin(
    bot: discord.Client,
    guild: discord.Guild,
    moderator: discord.Member,
    reason: str,
    channels: list[discord.TextChannel],
    duration_seconds: int | None,
) -> int:
    everyone = guild.default_role
    me = guild.me
    snapshot: dict[str, Any] = {}
    changed: list[discord.TextChannel] = []
    for channel in channels:
        if me is not None and not channel.permissions_for(me).manage_permissions:
            continue
        current = channel.overwrites_for(everyone)
        allow, deny = current.pair()
        snapshot[str(channel.id)] = {
            "existed": everyone in channel.overwrites,
            "allow": allow.value,
            "deny": deny.value,
        }
        current.send_messages = False
        await channel.set_permissions(everyone, overwrite=current, reason=reason[:200] or "Lockdown")
        changed.append(channel)
    if not changed:
        raise RuntimeError("I couldn't update any channels. I need Manage Permissions in those channels.")

    number = await open_case(
        bot,
        guild=guild,
        case_type=CaseType.LOCKDOWN,
        target_id=guild.id,
        moderator_id=moderator.id,
        reason=reason or f"Locked {len(changed)} channels",
        template_key="lockdown",
    )
    expires_at = None
    if duration_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    factory = get_session_factory()
    async with factory() as session:
        case = await session.scalar(
            select(Case)
            .where(Case.guild_id == guild.id, Case.case_number == number)
            .limit(1)
        )
        row = await session.get(Lockdown, guild.id)
        if row is None:
            row = Lockdown(guild_id=guild.id)
            session.add(row)
        row.active = True
        row.reason = reason or f"Locked {len(changed)} channels"
        row.moderator_id = moderator.id
        row.snapshot = snapshot
        row.case_id = case.id if case else None
        row.started_at = datetime.now(timezone.utc)
        row.ended_at = None
        await session.flush()
        if expires_at is not None and case is not None:
            session.add(
                ScheduledAction(
                    guild_id=guild.id,
                    case_id=case.id,
                    action="unlock",
                    payload={"attempts": 0},
                    run_at=expires_at,
                )
            )
        await session.commit()
    get_cache().invalidate(guild.id)
    return number


async def lockdown_end(bot: discord.Client, guild: discord.Guild, note: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(Lockdown, guild.id)
        if row is None or not row.active:
            return False
        snapshot = dict(row.snapshot or {})
        case_id = row.case_id
        row.active = False
        row.ended_at = datetime.now(timezone.utc)
        await session.commit()
    everyone = guild.default_role
    for raw_id, previous in snapshot.items():
        try:
            channel_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                fetched = await bot.fetch_channel(channel_id)
            except discord.HTTPException:
                continue
            channel = fetched if isinstance(fetched, discord.TextChannel) else None
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            if not previous.get("existed"):
                await channel.set_permissions(everyone, overwrite=None, reason=note)
            else:
                allow = discord.Permissions(int(previous.get("allow") or 0))
                deny = discord.Permissions(int(previous.get("deny") or 0))
                overwrite = discord.PermissionOverwrite.from_pair(allow, deny)
                await channel.set_permissions(everyone, overwrite=overwrite, reason=note)
        except discord.HTTPException:
            log.warning("failed to restore overwrite in %s", channel_id)
    if case_id is not None:
        await reverse_case(bot, case_id, note)
    get_cache().invalidate(guild.id)
    return True
