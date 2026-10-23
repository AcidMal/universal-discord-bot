from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands
from sqlalchemy import text

from shared.db import get_session_factory

log = logging.getLogger("bot.presence")

_bot: commands.Bot | None = None
_STATUSES = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}


def bind(bot: commands.Bot) -> None:
    global _bot
    _bot = bot


def schedule_apply() -> None:
    if _bot is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(apply_saved())


def _activity(kind: str, text: str) -> discord.BaseActivity | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if kind == "playing":
        return discord.Game(name=cleaned[:128])
    if kind == "watching":
        return discord.Activity(type=discord.ActivityType.watching, name=cleaned[:128])
    if kind == "listening":
        return discord.Activity(type=discord.ActivityType.listening, name=cleaned[:128])
    return discord.CustomActivity(name=cleaned[:128])


async def apply_saved() -> None:
    bot = _bot
    if bot is None or not bot.is_ready():
        return
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT presence, activity_type, status_text
                    FROM bot_profile
                    WHERE id = 1
                    """
                )
            )
        ).mappings().first()
    if row is None:
        return
    status = _STATUSES.get(str(row["presence"]), discord.Status.online)
    activity = _activity(str(row["activity_type"]), str(row["status_text"] or ""))
    try:
        await bot.change_presence(status=status, activity=activity)
    except discord.HTTPException:
        log.exception("could not update bot presence")
