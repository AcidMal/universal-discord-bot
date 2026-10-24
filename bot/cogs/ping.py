from __future__ import annotations

import math
import time

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import text

from bot.cache import get_cache
from shared.db import get_session_factory

_DESCRIPTION_LIMIT = 3900


def _latency_ms(shard: object) -> int | None:
    latency = getattr(shard, "latency", None)
    if latency is None or not math.isfinite(latency):
        return None
    return max(0, int(latency * 1000))


def _live_shard_latency(bot: commands.Bot) -> dict[int, int]:
    shards = getattr(bot, "shards", None) or {}
    found: dict[int, int] = {}
    for shard_id, shard in shards.items():
        latency_ms = _latency_ms(shard)
        if latency_ms is not None:
            found[int(shard_id)] = latency_ms
    if found:
        return found
    latency_ms = _latency_ms(bot)
    shard_id = getattr(bot, "shard_id", None)
    if latency_ms is not None:
        found[0 if shard_id is None else int(shard_id)] = latency_ms
    return found


def _age_label(seconds: float) -> str:
    if seconds < 1:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    return f"{int(seconds // 60)}m ago"


def _ms_label(value: int | None) -> str:
    if value is None:
        return "no reply"
    return f"{value} ms"


def _accent_color(accent: str) -> int:
    raw = accent.removeprefix("#")
    try:
        return int(raw, 16)
    except ValueError:
        return 0x7C5CFF


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Ping the cluster nodes and their shards")
    @app_commands.guild_only()
    async def ping(self, interaction: discord.Interaction) -> None:
        live = _live_shard_latency(self.bot)
        started = time.perf_counter()
        factory = get_session_factory()
        async with factory() as session:
            nodes = (
                await session.execute(
                    text(
                        """
                        SELECT node_id, hostname, role,
                               EXTRACT(EPOCH FROM (now() - last_seen)) AS age_seconds
                        FROM cluster_nodes
                        ORDER BY role, hostname, node_id
                        """
                    )
                )
            ).mappings().all()
            shards = (
                await session.execute(
                    text(
                        """
                        SELECT shard_id, node_id, gateway_status, latency_ms,
                               leased_until > now() AS lease_valid
                        FROM shard_leases
                        ORDER BY shard_id
                        """
                    )
                )
            ).mappings().all()
        database_ms = max(0, int((time.perf_counter() - started) * 1000))

        grouped: dict[str, list[str]] = {}
        ready = 0
        for shard in shards:
            shard_id = int(shard["shard_id"])
            status = str(shard["gateway_status"] or "unknown")
            node_id = shard["node_id"]
            if not shard["lease_valid"]:
                status = "expired" if node_id else "open"
            elif status == "ready":
                ready += 1
            latency_ms = live.get(shard_id)
            if latency_ms is None and shard["latency_ms"] is not None:
                latency_ms = int(shard["latency_ms"])
            grouped.setdefault(str(node_id) if node_id else "", []).append(
                f"shard {shard_id} · {status} · {_ms_label(latency_ms)}"
            )

        lines = [f"Database {_ms_label(database_ms)}"]
        online = 0
        for node in nodes:
            age = float(node["age_seconds"] or 0)
            if age < 20:
                status = "online"
                online += 1
            elif age < 60:
                status = "stale"
            else:
                status = "offline"
            node_id = str(node["node_id"])
            name = node["hostname"] or node_id
            role = node["role"] or "gateway"
            lines.append("")
            lines.append(f"**{name}** · {role} · {status} · {_age_label(age)}")
            lines.extend(grouped.get(node_id, ["no shards"]))

        unassigned = grouped.get("", [])
        if unassigned:
            lines.append("")
            lines.append("**Unassigned shards**")
            lines.extend(unassigned)

        description = "\n".join(lines)
        if len(description) > _DESCRIPTION_LIMIT:
            description = description[: _DESCRIPTION_LIMIT - 1].rstrip() + "…"

        accent = "#7C5CFF"
        if interaction.guild is not None:
            try:
                accent = (await get_cache().get(interaction.guild.id)).theme.accent or accent
            except Exception:
                pass
        embed = discord.Embed(
            title="Ping",
            description=description,
            color=_accent_color(accent),
        )
        embed.set_footer(text=f"{online}/{len(nodes)} nodes online · {ready}/{len(shards)} shards ready")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Ping(bot))
