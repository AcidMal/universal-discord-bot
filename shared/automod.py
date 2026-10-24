"""Shared automod rule shapes used by the dashboard and slash commands."""

from __future__ import annotations

import re
from typing import Any

ACTIONS = ("delete", "warn", "timeout", "kick", "ban")
MESSAGE_ACTIONS = ACTIONS
RAID_ACTIONS = ("warn", "timeout", "kick", "ban")

TYPE_HELP = {
    "words": "Punish a message that contains one of these words.",
    "links": "Punish a message that contains a link. Leave allowed domains empty to block every link.",
    "mentions": "Punish a message with more mentions than the limit.",
    "spam": "Punish someone who sends too many messages in a short time.",
    "raid": "Punish new members when too many people join in a short time.",
}


def format_seconds(seconds: int) -> str:
    if seconds % 86400 == 0 and seconds >= 86400:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0 and seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0 and seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        items = [str(item) for item in value]
    else:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        token = item.strip()
        key = token.lower()
        if not token or key in seen:
            continue
        seen.add(key)
        cleaned.append(token)
    return cleaned


def _whole_number(value: Any, default: int, *, low: int, high: int, label: str) -> int:
    if value is None or value == "":
        number = default
    else:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} needs a whole number.") from exc
    if number < low or number > high:
        raise ValueError(f"{label} must be between {low} and {high}.")
    return number


def normalize_config(rule_type: str, action: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return the config the engine reads, or raise ValueError with a short reason."""
    source = raw or {}
    if rule_type == "raid" and action == "delete":
        raise ValueError("A join raid needs warn, timeout, kick, or ban.")
    if rule_type == "words":
        words = _strings(source.get("words"))
        if not words:
            raise ValueError("Add at least one word.")
        if len(words) > 100:
            raise ValueError("Use 100 words or fewer.")
        if any(len(word) > 80 for word in words):
            raise ValueError("Each word must be 80 characters or fewer.")
        config: dict[str, Any] = {"words": words, "whole_word": bool(source.get("whole_word", False))}
    elif rule_type == "links":
        domains = _strings(source.get("allow_domains"))
        if len(domains) > 50:
            raise ValueError("Use 50 allowed domains or fewer.")
        config = {"allow_domains": domains}
    elif rule_type == "mentions":
        config = {
            "max_mentions": _whole_number(
                source.get("max_mentions"), 5, low=1, high=25, label="Mention limit"
            )
        }
    elif rule_type == "spam":
        config = {
            "max_messages": _whole_number(
                source.get("max_messages"), 5, low=2, high=30, label="Message limit"
            ),
            "window_seconds": _whole_number(
                source.get("window_seconds"), 7, low=2, high=600, label="Time window"
            ),
        }
    elif rule_type == "raid":
        config = {
            "max_joins": _whole_number(source.get("max_joins"), 8, low=2, high=50, label="Join limit"),
            "window_seconds": _whole_number(
                source.get("window_seconds"), 10, low=2, high=600, label="Time window"
            ),
        }
    else:
        raise ValueError("Unknown rule type.")
    if action == "timeout":
        config["timeout_seconds"] = _whole_number(
            source.get("timeout_seconds"),
            600,
            low=1,
            high=28 * 86400,
            label="Timeout length",
        )
    return config


def describe_rule(rule_type: str, action: str, config: dict[str, Any] | None) -> str:
    source = config or {}
    if rule_type == "words":
        words = [str(item) for item in source.get("words") or []]
        shown = ", ".join(words[:8])
        if len(words) > 8:
            shown = f"{shown}, +{len(words) - 8} more"
        mode = "as whole words" if source.get("whole_word") else "anywhere in the message"
        detail = f"Matches {shown or 'nothing'} {mode}."
    elif rule_type == "links":
        domains = [str(item) for item in source.get("allow_domains") or []]
        if domains:
            detail = f"Blocks links except {', '.join(domains[:8])}."
        else:
            detail = "Blocks every link and Discord invite."
    elif rule_type == "mentions":
        detail = f"More than {int(source.get('max_mentions') or 5)} mentions in one message."
    elif rule_type == "spam":
        detail = (
            f"More than {int(source.get('max_messages') or 5)} messages "
            f"in {format_seconds(int(source.get('window_seconds') or 7))}."
        )
    elif rule_type == "raid":
        detail = (
            f"More than {int(source.get('max_joins') or 8)} joins "
            f"in {format_seconds(int(source.get('window_seconds') or 10))}."
        )
    else:
        detail = rule_type
    if action == "timeout":
        length = format_seconds(int(source.get("timeout_seconds") or 600))
        return f"{detail} Then timeout for {length}."
    labels = {"delete": "delete the message", "warn": "warn", "kick": "kick", "ban": "ban"}
    if action == "delete":
        return f"{detail} Then delete the message."
    return f"{detail} Then {labels.get(action, action)}."
