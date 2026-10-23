from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

EMBED_TEMPLATE_KEYS = ("case", "mod_log", "report", "lockdown", "automod")

DEFAULT_EMBED_TEMPLATES: dict[str, dict[str, str]] = {
    "case": {
        "title": "Case #{case}",
        "description": "{reason}",
    },
    "mod_log": {
        "title": "{type} · #{case}",
        "description": "{target}\n{reason}",
    },
    "report": {
        "title": "Report",
        "description": "{reason}",
    },
    "lockdown": {
        "title": "Lockdown",
        "description": "{reason}",
    },
    "automod": {
        "title": "Automod",
        "description": "{reason}",
    },
}


class ThemeLike(Protocol):
    accent: str
    logo_url: str | None
    footer: str
    author_name: str
    embed_templates: dict[str, Any]
    background: str
    surface: str
    text: str
    radius: str


@dataclass(frozen=True)
class ThemePreset:
    name: str
    accent: str
    background: str
    surface: str
    text: str
    radius: str = "8px"
    footer: str = ""
    author_name: str = ""
    logo_url: str | None = None
    embed_templates: dict[str, dict[str, str]] = field(
        default_factory=lambda: {k: dict(v) for k, v in DEFAULT_EMBED_TEMPLATES.items()}
    )


PRESETS: dict[str, ThemePreset] = {
    "midnight": ThemePreset(
        name="Midnight",
        accent="#7C5CFF",
        background="#0B0C10",
        surface="#15171E",
        text="#E8EAF0",
    ),
    "light": ThemePreset(
        name="Light",
        accent="#4F46E5",
        background="#F7F7F5",
        surface="#FFFFFF",
        text="#111318",
    ),
    "nord": ThemePreset(
        name="Nord",
        accent="#88C0D0",
        background="#2E3440",
        surface="#3B4252",
        text="#ECEFF4",
    ),
    "rose": ThemePreset(
        name="Rose",
        accent="#E11D48",
        background="#1C1418",
        surface="#2A1D22",
        text="#FDE8EE",
    ),
}


def get_preset(name: str) -> ThemePreset:
    key = name.strip().lower()
    if key not in PRESETS:
        raise KeyError(f"Unknown theme preset: {name}")
    return PRESETS[key]


def _substitute(template: str, substitutions: dict[str, str]) -> str:
    out = template
    for key, value in substitutions.items():
        out = out.replace("{" + key + "}", value)
    return out


def render_embed(
    theme: ThemeLike,
    template_key: str,
    substitutions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a discord.py-compatible embed dict from constrained template fields."""
    if template_key not in EMBED_TEMPLATE_KEYS:
        raise KeyError(f"Unknown embed template: {template_key}")
    substitutions = substitutions or {}
    templates = theme.embed_templates or DEFAULT_EMBED_TEMPLATES
    block = templates.get(template_key) or DEFAULT_EMBED_TEMPLATES[template_key]
    color_hex = theme.accent.lstrip("#")
    color = int(color_hex, 16) if color_hex else 0
    embed: dict[str, Any] = {
        "title": _substitute(str(block.get("title", "")), substitutions),
        "description": _substitute(str(block.get("description", "")), substitutions),
        "color": color,
    }
    if theme.footer:
        embed["footer"] = {"text": _substitute(theme.footer, substitutions)}
    if theme.author_name:
        embed["author"] = {"name": _substitute(theme.author_name, substitutions)}
    if theme.logo_url:
        embed["thumbnail"] = {"url": theme.logo_url}
    return embed


def render_css_tokens(theme: ThemeLike) -> dict[str, str]:
    """Map a guild theme row to dashboard CSS custom properties."""
    return {
        "--accent": theme.accent,
        "--bg": theme.background,
        "--surface": theme.surface,
        "--text": theme.text,
        "--radius": theme.radius,
    }


def css_variables_block(theme: ThemeLike) -> str:
    tokens = render_css_tokens(theme)
    inner = ";\n".join(f"  {name}: {value}" for name, value in tokens.items())
    return f":root {{\n{inner};\n}}\n"
