from __future__ import annotations

import discord
from discord.ext import commands

EXTENSIONS = (
    "bot.cogs.core",
    "bot.cogs.ping",
    "bot.cogs.setup",
    "bot.cogs.cases",
    "bot.cogs.notes",
    "bot.cogs.reports",
    "bot.cogs.tickets",
    "bot.cogs.lockdown",
    "bot.cogs.automod",
    "bot.cogs.theme",
    "bot.cogs.twitch",
    "bot.scheduler",
)


class ModBot(commands.AutoShardedBot):
    cluster_node_id: str = ""

    def __init__(self, *, shard_ids: list[int], shard_count: int) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            shard_ids=shard_ids,
            shard_count=shard_count,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        for extension in EXTENSIONS:
            await self.load_extension(extension)


def create_bot(*, shard_ids: list[int], shard_count: int) -> ModBot:
    return ModBot(shard_ids=shard_ids, shard_count=shard_count)
