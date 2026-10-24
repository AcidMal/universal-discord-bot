from __future__ import annotations

import logging
import uuid
from typing import Any

import discord
from discord.ext import commands, tasks
from sqlalchemy import text

from bot.actions import lockdown_end, reverse_case
from shared.db import get_session_factory
from shared.enums import AuditSource
from shared.services import add_audit

log = logging.getLogger("bot.scheduler")

CLAIM_SQL = """
WITH picked AS (
    SELECT id
    FROM scheduled_actions
    WHERE done_at IS NULL
      AND run_at <= now()
      AND (claimed_at IS NULL OR claimed_at < now() - interval '60 seconds')
    ORDER BY run_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE scheduled_actions AS job
SET claimed_by = :node, claimed_at = now()
FROM picked
WHERE job.id = picked.id
RETURNING job.id, job.guild_id, job.case_id, job.action, job.payload
"""


async def _claim(node_id: str) -> dict[str, Any] | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(text(CLAIM_SQL), {"node": node_id})
        row = result.mappings().first()
        await session.commit()
        return dict(row) if row else None


async def _finish(job_id: uuid.UUID, *, done: bool, payload: dict[str, Any]) -> None:
    factory = get_session_factory()
    async with factory() as session:
        if done:
            await session.execute(
                text(
                    """
                    UPDATE scheduled_actions
                    SET done_at = now(), payload = CAST(:payload AS jsonb)
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "payload": _json(payload)},
            )
        else:
            await session.execute(
                text(
                    """
                    UPDATE scheduled_actions
                    SET claimed_by = NULL, claimed_at = NULL, payload = CAST(:payload AS jsonb)
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "payload": _json(payload)},
            )
        await session.commit()


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload)


async def _execute(bot: commands.Bot, job: dict[str, Any]) -> None:
    guild_id = int(job["guild_id"])
    action = str(job["action"])
    payload = dict(job["payload"] or {})
    guild = bot.get_guild(guild_id)
    if guild is None:
        guild = await bot.fetch_guild(guild_id)
    if action == "unban":
        user_id = int(payload["user_id"])
        await guild.unban(discord.Object(id=user_id), reason="Timed ban expired")
    elif action == "untimeout":
        user_id = int(payload["user_id"])
        member = guild.get_member(user_id)
        if member is None:
            member = await guild.fetch_member(user_id)
        await member.timeout(None, reason="Timed timeout expired")
    elif action == "unlock":
        restored = await lockdown_end(bot, guild, "Timed lockdown ended")
        if not restored:
            log.info("unlock skipped; guild %s was not locked", guild_id)
    elif action == "delete_message":
        channel_id = int(payload["channel_id"])
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        message = await channel.fetch_message(int(payload["message_id"]))
        await message.delete()
        return
    else:
        raise RuntimeError(f"unknown scheduled action {action}")
    case_id = job["case_id"]
    if case_id is not None and action != "unlock":
        await reverse_case(bot, case_id, f"Scheduled {action} completed")
    factory = get_session_factory()
    async with factory() as session:
        await add_audit(
            session,
            guild_id=guild_id,
            actor_id=None,
            action=f"schedule.{action}",
            source=AuditSource.SCHEDULER,
            target_type="case",
            target_id=str(case_id) if case_id else None,
            payload={"job_id": str(job["id"])},
        )
        await session.commit()


async def drain_jobs(bot: commands.Bot) -> None:
    node_id = getattr(bot, "cluster_node_id", "")
    for _ in range(10):
        job = await _claim(node_id)
        if job is None:
            return
        payload = dict(job["payload"] or {})
        try:
            await _execute(bot, job)
        except Exception:
            log.exception("scheduled action %s failed", job["id"])
            attempts = int(payload.get("attempts") or 0) + 1
            payload["attempts"] = attempts
            await _finish(job["id"], done=attempts >= 5, payload=payload)
        else:
            await _finish(job["id"], done=True, payload=payload)


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runner.start()

    def cog_unload(self) -> None:
        self.runner.cancel()

    @tasks.loop(seconds=2)
    async def runner(self) -> None:
        await drain_jobs(self.bot)

    @runner.before_loop
    async def before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Scheduler(bot))
