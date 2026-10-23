from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.db import get_session_factory
from shared.services import load_guild_bundle
from shared.theme import DEFAULT_EMBED_TEMPLATES, PRESETS, ThemePreset


@dataclass
class RuleView:
    id: str
    type: str
    name: str
    config: dict[str, Any]
    action: str


@dataclass
class StaffView:
    role_id: int
    can_warn: bool
    can_timeout: bool
    can_kick: bool
    can_ban: bool


@dataclass
class GuildState:
    log_channel_id: int | None
    timezone: str
    timeout_default_seconds: int
    module_toggles: dict[str, Any]
    ignored_channel_ids: set[int]
    ignored_role_ids: set[int]
    theme: ThemePreset
    rules: list[RuleView] = field(default_factory=list)
    staff: list[StaffView] = field(default_factory=list)


def _as_int_set(values: list[Any] | None) -> set[int]:
    found: set[int] = set()
    for value in values or []:
        try:
            found.add(int(value))
        except (TypeError, ValueError):
            continue
    return found


def _theme_from_row(theme) -> ThemePreset:
    if theme is None:
        return PRESETS["midnight"]
    templates = theme.embed_templates or DEFAULT_EMBED_TEMPLATES
    return ThemePreset(
        name=theme.preset or "custom",
        accent=theme.accent,
        background=theme.background,
        surface=theme.surface,
        text=theme.text,
        radius=theme.radius or "8px",
        footer=theme.footer or "",
        author_name=theme.author_name or "",
        logo_url=theme.logo_url,
        embed_templates={key: dict(value) for key, value in templates.items()},
    )


class GuildCache:
    def __init__(self) -> None:
        self._states: dict[int, GuildState] = {}

    def invalidate(self, guild_id: int | None) -> None:
        if guild_id is None:
            self._states.clear()
            return
        self._states.pop(guild_id, None)

    async def get(self, guild_id: int) -> GuildState:
        cached = self._states.get(guild_id)
        if cached is not None:
            return cached
        factory = get_session_factory()
        async with factory() as session:
            bundle = await load_guild_bundle(session, guild_id)
            config = bundle["config"]
            state = GuildState(
                log_channel_id=config.log_channel_id if config else None,
                timezone=config.timezone if config else "UTC",
                timeout_default_seconds=config.timeout_default_seconds if config else 600,
                module_toggles=dict(config.module_toggles) if config else {},
                ignored_channel_ids=_as_int_set(config.ignored_channel_ids if config else []),
                ignored_role_ids=_as_int_set(config.ignored_role_ids if config else []),
                theme=_theme_from_row(bundle["theme"]),
                rules=[
                    RuleView(
                        id=str(rule.id),
                        type=rule.type,
                        name=rule.name,
                        config=dict(rule.config or {}),
                        action=rule.action,
                    )
                    for rule in bundle["rules"]
                ],
                staff=[
                    StaffView(
                        role_id=row.role_id,
                        can_warn=row.can_warn,
                        can_timeout=row.can_timeout,
                        can_kick=row.can_kick,
                        can_ban=row.can_ban,
                    )
                    for row in bundle["staff"]
                ],
            )
        self._states[guild_id] = state
        return state


_cache = GuildCache()


def get_cache() -> GuildCache:
    return _cache
