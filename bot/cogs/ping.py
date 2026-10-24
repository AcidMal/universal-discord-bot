from __future__ import annotations

import math
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import text

from shared.db import get_session_factory

_ONLINE_SECONDS = 20
_LIVE_SECONDS = 60
_MARK = {
    "online": "🟢",
    "ready": "🟢",
    "stale": "🟡",
    "connecting": "🟡",
    "disconnected": "🔴",
    "expired": "🔴",
    "offline": "🔴",
    "open": "⚪",
    "unknown": "⚪",
}
_COLOR = {
    "online": 0x57F287,
    "stale": 0xFEE75C,
    "disconnected": 0xED4245,
    "open": 0x99AAB5,
}


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


def _mark(status: str) -> str:
    return _MARK.get(status, "⚪")


def _node_status(age: float) -> str | None:
    if age < _ONLINE_SECONDS:
        return "online"
    if age < _LIVE_SECONDS:
        return "stale"
    return None


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Ping the live cluster nodes and their shards")
    @app_commands.guild_only()
    async def ping(self, interaction: discord.Interaction) -> None:
        live_latency = _live_shard_latency(self.bot)
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
                        WHERE last_seen > now() - (:live_seconds * interval '1 second')
                        ORDER BY role, hostname, node_id
                        """
                    ),
                    {"live_seconds": _LIVE_SECONDS},
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

        live_ids = {str(node["node_id"]) for node in nodes}
        grouped: dict[str, list[str]] = {}
        ready = 0
        shown_shards = 0
        unassigned: list[str] = []
        for shard in shards:
            line, status = _shard_line(shard, live_latency)
            node_id = str(shard["node_id"]) if shard["node_id"] else ""
            if node_id in live_ids:
                grouped.setdefault(node_id, []).append(line)
                shown_shards += 1
                if status == "ready":
                    ready += 1
            elif not node_id or not shard["lease_valid"]:
                open_line, _status = _shard_line({**dict(shard), "node_id": None}, live_latency)
                unassigned.append(open_line)

        embeds = [_summary_embed(database_ms, nodes, ready, shown_shards)]
        for node in nodes:
            if len(embeds) >= 10:
                break
            embeds.append(_node_embed(node, grouped.get(str(node["node_id"]), [])))
        if unassigned and len(embeds) < 10:
            embeds.append(_unassigned_embed(unassigned))
        await interaction.response.send_message(embeds=embeds[:10])


def _shard_line(shard: Any, live_latency: dict[int, int]) -> tuple[str, str]:
    shard_id = int(shard["shard_id"])
    status = str(shard["gateway_status"] or "unknown")
    if not shard["lease_valid"]:
        status = "expired" if shard["node_id"] else "open"
    latency_ms = live_latency.get(shard_id)
    if latency_ms is None and shard["latency_ms"] is not None:
        latency_ms = int(shard["latency_ms"])
    return f"{_mark(status)} shard {shard_id} · {status} · {_ms_label(latency_ms)}", status


def _summary_embed(database_ms: int, nodes: list[Any], ready: int, shown_shards: int) -> discord.Embed:
    online = sum(1 for node in nodes if _node_status(float(node["age_seconds"] or 0)) == "online")
    if not nodes:
        color = _COLOR["open"]
    elif online == len(nodes) and (shown_shards == 0 or ready == shown_shards):
        color = _COLOR["online"]
    elif online == 0:
        color = _COLOR["disconnected"]
    else:
        color = _COLOR["stale"]
    embed = discord.Embed(
        title="Ping",
        description=f"{_mark('online')} Database {_ms_label(database_ms)}",
        color=color,
    )
    embed.set_footer(text=f"{online}/{len(nodes)} live nodes · {ready}/{shown_shards} shards ready")
    return embed


def _node_embed(node: Any, shard_lines: list[str]) -> discord.Embed:
    age = float(node["age_seconds"] or 0)
    status = _node_status(age) or "offline"
    name = node["hostname"] or str(node["node_id"])
    role = node["role"] or "gateway"
    embed = discord.Embed(
        title=f"{_mark(status)} {name}",
        description=f"{status} · {role} · heartbeat {_age_label(age)}",
        color=_COLOR["online"] if status == "online" else _COLOR["stale"],
    )
    body = "\n".join(shard_lines) if shard_lines else "⚪ no shards"
    embed.add_field(name="Shards", value=body[:1024], inline=False)
    return embed


def _unassigned_embed(lines: list[str]) -> discord.Embed:
    embed = discord.Embed(title="⚪ Unassigned shards", color=_COLOR["open"])
    embed.description = "\n".join(lines)[:4096]
    return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Ping(bot))
