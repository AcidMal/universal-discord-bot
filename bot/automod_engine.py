from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import discord

from bot.access import member_can
from bot.actions import open_case
from bot.cache import GuildState, RuleView, get_cache
from shared.db import get_session_factory
from shared.enums import AuditSource, AutomodAction, CaseType
from shared.services import bump_window, claim_event

LINK_RE = re.compile(r"(https?://[^\s<]+|discord\.gg/[^\s<]+)", re.IGNORECASE)
SEVERITY = {
    AutomodAction.BAN: 5,
    AutomodAction.KICK: 4,
    AutomodAction.TIMEOUT: 3,
    AutomodAction.WARN: 2,
    AutomodAction.DELETE: 1,
}


@dataclass
class Hit:
    rule: RuleView
    detail: str
    count: int | None = None


def _host(url: str) -> str:
    if url.lower().startswith("discord.gg/"):
        return "discord.gg"
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return (parsed.hostname or "").lower()


def _allowed_link(url: str, allow_domains: list[str]) -> bool:
    host = _host(url)
    if not host:
        return False
    for domain in allow_domains:
        cleaned = domain.lower().strip().lstrip(".")
        if cleaned and (host == cleaned or host.endswith(f".{cleaned}")):
            return True
    return False


def _word_hit(content: str, words: list[str], whole: bool) -> str | None:
    lowered = content.lower()
    for word in words:
        token = str(word).strip().lower()
        if not token:
            continue
        if whole:
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                return token
        elif token in lowered:
            return token
    return None


def message_hits(message: discord.Message, state: GuildState) -> list[Hit]:
    content = message.content or ""
    hits: list[Hit] = []
    for rule in state.rules:
        config = rule.config or {}
        if rule.type == "words":
            matched = _word_hit(content, list(config.get("words") or []), bool(config.get("whole_word")))
            if matched:
                hits.append(Hit(rule, f"blocked word `{matched}`"))
        elif rule.type == "links":
            urls = LINK_RE.findall(content)
            allow = [str(item) for item in (config.get("allow_domains") or [])]
            blocked = [url for url in urls if not _allowed_link(url, allow)]
            if blocked:
                hits.append(Hit(rule, "blocked link"))
        elif rule.type == "mentions":
            limit = int(config.get("max_mentions") or 5)
            count = len(message.mentions) + len(message.role_mentions)
            if message.mention_everyone:
                count += 1
            if count > limit:
                hits.append(Hit(rule, f"{count} mentions"))
    return hits


async def count_hit(
    guild_id: int,
    key: str,
    *,
    seconds: int,
    limit: int,
    edge_only: bool,
) -> int | None:
    factory = get_session_factory()
    async with factory() as session:
        count = await bump_window(session, guild_id, key, seconds)
        await session.commit()
    if edge_only:
        return count if count == limit else None
    return count if count >= limit else None


def pick_hit(hits: list[Hit]) -> Hit | None:
    if not hits:
        return None
    return max(hits, key=lambda hit: SEVERITY.get(hit.rule.action, 0))


def bypasses_automod(member: discord.Member, state: GuildState) -> bool:
    if member.bot:
        return True
    if member.guild_permissions.manage_messages or member.guild_permissions.administrator:
        return True
    return member_can(member, "warn", state)


async def punish(
    bot: discord.Client,
    guild: discord.Guild,
    target: discord.Member | discord.User,
    hit: Hit,
    *,
    message: discord.Message | None,
    event_id: str,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        fresh = await claim_event(session, event_id)
        await session.commit()
    if not fresh:
        return
    if message is not None:
        try:
            await message.delete()
        except discord.HTTPException:
            pass
    action = hit.rule.action
    reason = f"Automod ({hit.rule.name or hit.rule.type}): {hit.detail}"
    duration = None
    schedule = None
    case_type = CaseType.WARN
    if action == AutomodAction.DELETE:
        case_type = CaseType.WARN
    elif action == AutomodAction.WARN:
        case_type = CaseType.WARN
    elif action == AutomodAction.TIMEOUT and isinstance(target, discord.Member):
        case_type = CaseType.TIMEOUT
        duration = int(hit.rule.config.get("timeout_seconds") or 600)
        schedule = "untimeout"
        try:
            from datetime import timedelta

            await target.timeout(timedelta(seconds=duration), reason=reason[:200])
        except discord.HTTPException:
            pass
    elif action == AutomodAction.KICK and isinstance(target, discord.Member):
        case_type = CaseType.KICK
        try:
            await target.kick(reason=reason[:200])
        except discord.HTTPException:
            pass
    elif action == AutomodAction.BAN:
        case_type = CaseType.BAN
        try:
            await guild.ban(target, reason=reason[:200], delete_message_seconds=0)
        except discord.HTTPException:
            pass
    if action == AutomodAction.DELETE:
        return
    await open_case(
        bot,
        guild=guild,
        case_type=case_type,
        target_id=target.id,
        moderator_id=None,
        reason=reason,
        duration_seconds=duration,
        schedule_action=schedule,
        source=AuditSource.AUTOMOD,
        template_key="automod",
    )


async def handle_message(bot: discord.Client, message: discord.Message) -> None:
    if message.guild is None or not isinstance(message.author, discord.Member):
        return
    state = await get_cache().get(message.guild.id)
    if not state.module_toggles.get("automod", True):
        return
    if message.channel.id in state.ignored_channel_ids:
        return
    if any(role.id in state.ignored_role_ids for role in message.author.roles):
        return
    if bypasses_automod(message.author, state):
        return
    hits = message_hits(message, state)
    for rule in state.rules:
        if rule.type != "spam":
            continue
        limit = int(rule.config.get("max_messages") or 5)
        window = int(rule.config.get("window_seconds") or 7)
        count = await count_hit(
            message.guild.id,
            f"spam:{message.author.id}",
            seconds=window,
            limit=limit,
            edge_only=True,
        )
        if count is not None:
            hits.append(Hit(rule, f"{count} messages in {window}s", count))
    chosen = pick_hit(hits)
    if chosen is None:
        return
    await punish(
        bot,
        message.guild,
        message.author,
        chosen,
        message=message,
        event_id=f"msg:{message.id}:rule:{chosen.rule.id}",
    )


async def handle_join(bot: discord.Client, member: discord.Member) -> None:
    if member.bot:
        return
    state = await get_cache().get(member.guild.id)
    if not state.module_toggles.get("automod", True):
        return
    hits: list[Hit] = []
    for rule in state.rules:
        if rule.type != "raid":
            continue
        limit = int(rule.config.get("max_joins") or 8)
        window = int(rule.config.get("window_seconds") or 10)
        count = await count_hit(
            member.guild.id,
            "raid",
            seconds=window,
            limit=limit,
            edge_only=False,
        )
        if count is not None:
            hits.append(Hit(rule, f"{count} joins in {window}s", count))
    chosen = pick_hit(hits)
    if chosen is None:
        return
    await punish(
        bot,
        member.guild,
        member,
        chosen,
        message=None,
        event_id=f"join:{member.guild.id}:{member.id}:rule:{chosen.rule.id}",
    )
