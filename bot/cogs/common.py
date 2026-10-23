from __future__ import annotations

import discord
from discord import app_commands

from bot.access import member_can, module_enabled
from bot.cache import get_cache
from shared.services import ensure_guild
from shared.db import get_session_factory


async def deny(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def prepare(
    interaction: discord.Interaction,
    action: str,
    module: str | None = None,
) -> bool:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await deny(interaction, "Use this command in a server.")
        return False
    factory = get_session_factory()
    async with factory() as session:
        await ensure_guild(session, interaction.guild.id, interaction.guild.name)
        await session.commit()
    get_cache().invalidate(interaction.guild.id)
    state = await get_cache().get(interaction.guild.id)
    if module is not None and not module_enabled(state, module):
        await deny(interaction, f"The {module} module is turned off for this server.")
        return False
    if not member_can(interaction.user, action, state):
        await deny(interaction, "You don't have permission to do that.")
        return False
    return True


def guild_only(command: app_commands.Command) -> app_commands.Command:
    return app_commands.guild_only()(command)
