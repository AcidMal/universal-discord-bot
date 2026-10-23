from __future__ import annotations

import discord
from discord.ext import commands


def create_bot() -> commands.Bot:
    """Build a Bot instance. Shard ids / shard_count are assigned by cluster leasing later."""
    intents = discord.Intents.default()
    return commands.Bot(command_prefix="!", intents=intents)
