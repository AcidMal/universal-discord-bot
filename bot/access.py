from __future__ import annotations

import discord

from bot.cache import GuildState

_STAFF_FLAG = {
    "warn": "can_warn",
    "timeout": "can_timeout",
    "kick": "can_kick",
    "ban": "can_ban",
    "unban": "can_ban",
    "notes": "can_warn",
    "reports_staff": "can_warn",
    "tickets": "can_warn",
    "lockdown": "can_ban",
}


def module_enabled(state: GuildState, name: str) -> bool:
    return bool(state.module_toggles.get(name, True))


def member_can(member: discord.Member, action: str, state: GuildState) -> bool:
    perms = member.guild_permissions
    if perms.administrator:
        return True
    native = False
    if action == "ticket_open":
        return True
    if action in {"warn", "timeout", "notes", "reports_staff", "tickets"}:
        native = perms.moderate_members or perms.manage_guild or (action == "tickets" and perms.manage_channels)
    elif action == "kick":
        native = perms.kick_members
    elif action in {"ban", "unban"}:
        native = perms.ban_members
    elif action in {"setup", "theme", "automod", "twitch"}:
        native = perms.manage_guild
    elif action == "lockdown":
        native = perms.manage_channels or perms.manage_guild
    if native:
        return True
    flag = _STAFF_FLAG.get(action)
    if flag is None:
        return False
    role_ids = {role.id for role in member.roles}
    for staff in state.staff:
        if staff.role_id in role_ids and getattr(staff, flag):
            return True
    return False


def hierarchy_problem(actor: discord.Member, target: discord.Member) -> str | None:
    if target.id == actor.id:
        return "You can't use that on yourself."
    me = actor.guild.me
    if me is not None and target.id == me.id:
        return "You can't use that on me."
    if target.guild_permissions.administrator and actor != actor.guild.owner:
        return "That member is an administrator."
    if actor != actor.guild.owner and target.top_role >= actor.top_role:
        return "That member is above your highest role."
    if me is not None and target.top_role >= me.top_role and actor != actor.guild.owner:
        return "That member is above my highest role."
    return None
