from __future__ import annotations

from enum import StrEnum


class CaseType(StrEnum):
    WARN = "warn"
    TIMEOUT = "timeout"
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    LOCKDOWN = "lockdown"


class ReportStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class AutomodRuleType(StrEnum):
    SPAM = "spam"
    RAID = "raid"
    MENTIONS = "mentions"
    LINKS = "links"
    WORDS = "words"


class AutomodAction(StrEnum):
    DELETE = "delete"
    TIMEOUT = "timeout"
    WARN = "warn"
    KICK = "kick"
    BAN = "ban"


class AuditSource(StrEnum):
    DASHBOARD = "dashboard"
    COMMAND = "command"
    AUTOMOD = "automod"
    SCHEDULER = "scheduler"
    SYSTEM = "system"
