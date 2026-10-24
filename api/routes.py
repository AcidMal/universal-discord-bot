from __future__ import annotations

import asyncio
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select

from api.discord_api import can_manage, discord_request
from api.security import STATE_COOKIE, clear_session, read_session, write_session
from shared.automod import describe_rule, normalize_config
from shared.db import get_session_factory
from shared.enums import AuditSource, AutomodAction, AutomodRuleType, ReportStatus
from shared.models import (
    AutomodRule,
    Case,
    Guild,
    GuildConfig,
    GuildTheme,
    MemberNote,
    Report,
    ScheduledAction,
    StaffRole,
    Ticket,
    TicketMessage,
    TwitchAlert,
    TwitchLiveState,
)
from shared.services import (
    add_audit,
    apply_preset,
    notes_for_target,
    notify_guild,
    reports_for_guild,
    upsert_staff_role,
)
from shared.settings import get_settings
from shared.twitch import TwitchError, delete_eventsub, ensure_eventsub, lookup_user, twitch_configured
from shared.twitch_format import normalize_login
from shared.theme import EMBED_TEMPLATE_KEYS, PRESETS, render_css_tokens, render_embed

router = APIRouter()
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
PLACEHOLDERS = {"{case}", "{type}", "{target}", "{reason}", "{moderator}"}
_GUILD_CACHE_SECONDS = 20.0
_guild_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_guild_locks: dict[str, asyncio.Lock] = {}


def _snow(value: int | None) -> str | None:
    return None if value is None else str(value)


def _parse_snow(value: str | None, field: str) -> int | None:
    if value is None or value == "":
        return None
    if not str(value).isdigit():
        raise HTTPException(status_code=422, detail=f"{field} must be a snowflake")
    return int(value)


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be an id") from exc


def _redirect_uri() -> str:
    return f"{get_settings().public_url}/auth/callback"


def _check_hex(value: str, field: str) -> str:
    if not HEX.match(value):
        raise HTTPException(status_code=422, detail=f"{field} must be a #RRGGBB color")
    return value


async def _member_role_ids(guild_id: int, user_id: str, token: str) -> set[int]:
    try:
        member = await discord_request(
            "GET",
            f"/guilds/{guild_id}/members/{user_id}",
            token=token,
            bot=True,
            timeout=5,
        )
    except HTTPException:
        return set()
    if not member:
        return set()
    return {int(role_id) for role_id in member.get("roles") or []}


async def _accessible_guilds(session_data: dict) -> list[dict[str, Any]]:
    user_id = str(session_data["user_id"])
    lock = _guild_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        cached = _guild_cache.get(user_id)
        now = time.monotonic()
        if cached is not None and now - cached[0] < _GUILD_CACHE_SECONDS:
            return cached[1]
        visible = await _load_accessible_guilds(session_data)
        _guild_cache[user_id] = (time.monotonic(), visible)
        return visible


async def _load_accessible_guilds(session_data: dict) -> list[dict[str, Any]]:
    settings = get_settings()
    oauth_guilds = await discord_request("GET", "/users/@me/guilds", token=session_data["access_token"])
    if oauth_guilds is None:
        raise HTTPException(status_code=401, detail="Discord session expired")
    factory = get_session_factory()
    async with factory() as session:
        rows = list((await session.scalars(select(Guild).where(Guild.left_at.is_(None)))).all())
        known = {row.id: row.name for row in rows}
        staff_rows: list[StaffRole] = []
        if known:
            staff_rows = list(
                (await session.scalars(select(StaffRole).where(StaffRole.guild_id.in_(list(known))))).all()
            )
    staff_by_guild: dict[int, set[int]] = {}
    for row in staff_rows:
        staff_by_guild.setdefault(row.guild_id, set()).add(row.role_id)

    visible: list[dict[str, Any]] = []
    pending: list[int] = []
    user_id = str(session_data["user_id"])
    for guild in oauth_guilds:
        guild_id = int(guild["id"])
        if guild_id not in known:
            continue
        permissions = int(guild.get("permissions") or 0)
        if guild.get("owner") or can_manage(permissions):
            visible.append({"id": str(guild_id), "name": known[guild_id], "access": "manager"})
            continue
        if staff_by_guild.get(guild_id) and settings.discord_token:
            pending.append(guild_id)

    if not pending:
        return visible

    semaphore = asyncio.Semaphore(4)

    async def lookup(guild_id: int) -> tuple[int, set[int]]:
        async with semaphore:
            return guild_id, await _member_role_ids(guild_id, user_id, settings.discord_token)

    for guild_id, role_ids in await asyncio.gather(*(lookup(guild_id) for guild_id in pending)):
        if role_ids & staff_by_guild.get(guild_id, set()):
            visible.append({"id": str(guild_id), "name": known[guild_id], "access": "staff"})
    return visible


async def _require_guild(request: Request, guild_id: int) -> dict[str, Any]:
    session_data = read_session(request)
    guilds = await _accessible_guilds(session_data)
    match = next((guild for guild in guilds if guild["id"] == str(guild_id)), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return session_data


@router.get("/auth/login")
async def login() -> Response:
    settings = get_settings()
    if not settings.discord_client_id or not settings.discord_client_secret:
        raise HTTPException(status_code=503, detail="Discord OAuth is not configured")
    state = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "client_id": settings.discord_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
        }
    )
    redirect = Response(status_code=302, headers={"Location": f"https://discord.com/oauth2/authorize?{query}"})
    redirect.set_cookie(
        STATE_COOKIE,
        state,
        httponly=True,
        samesite="lax",
        secure=settings.public_url.startswith("https"),
        max_age=600,
        path="/",
    )
    return redirect


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
    settings = get_settings()
    if error:
        raise HTTPException(status_code=400, detail=error)
    expected = request.cookies.get(STATE_COOKIE)
    if not code or not state or not expected or state != expected:
        raise HTTPException(status_code=400, detail="OAuth state did not match")
    token = await discord_request(
        "POST",
        "/oauth2/token",
        token="",
        form={
            "client_id": settings.discord_client_id,
            "client_secret": settings.discord_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
        },
    )
    if not token or "access_token" not in token:
        raise HTTPException(status_code=400, detail="Discord did not return a token")
    user = await discord_request("GET", "/users/@me", token=token["access_token"])
    if not user:
        raise HTTPException(status_code=400, detail="Discord did not return a user")
    redirect = Response(status_code=302, headers={"Location": settings.public_url + "/"})
    write_session(
        redirect,
        {
            "user_id": str(user["id"]),
            "username": user.get("global_name") or user.get("username") or "staff",
            "access_token": token["access_token"],
        },
    )
    redirect.delete_cookie(STATE_COOKIE, path="/")
    return redirect


@router.post("/auth/logout")
async def logout() -> Response:
    response = Response(status_code=204)
    clear_session(response)
    return response


@router.get("/api/me")
async def me(request: Request) -> dict[str, str | bool]:
    session_data = read_session(request)
    user_id = str(session_data["user_id"])
    return {
        "id": user_id,
        "username": str(session_data.get("username") or ""),
        "is_admin": user_id in get_settings().admin_id_set(),
    }


@router.get("/api/guilds")
async def guilds(request: Request) -> list[dict[str, Any]]:
    return await _accessible_guilds(read_session(request))


def _config_out(config: GuildConfig) -> dict[str, Any]:
    return {
        "locale": config.locale,
        "timezone": config.timezone,
        "log_channel_id": _snow(config.log_channel_id),
        "ticket_category_id": _snow(config.ticket_category_id),
        "timeout_default_seconds": config.timeout_default_seconds,
        "module_toggles": config.module_toggles,
        "ignored_channel_ids": [str(item) for item in config.ignored_channel_ids or []],
        "ignored_role_ids": [str(item) for item in config.ignored_role_ids or []],
    }


def _theme_out(theme: GuildTheme) -> dict[str, Any]:
    payload = {
        "preset": theme.preset,
        "accent": theme.accent,
        "background": theme.background,
        "surface": theme.surface,
        "text": theme.text,
        "radius": theme.radius,
        "footer": theme.footer,
        "author_name": theme.author_name,
        "logo_url": theme.logo_url,
        "embed_templates": theme.embed_templates,
        "tokens": render_css_tokens(theme),
    }
    payload["preview"] = render_embed(
        theme,
        "case",
        {
            "case": "42",
            "type": "warn",
            "target": "member",
            "reason": "Preview case. Nothing was saved.",
            "moderator": "staff",
        },
    )
    return payload


class ConfigPatch(BaseModel):
    locale: str | None = None
    timezone: str | None = None
    log_channel_id: str | None = None
    ticket_category_id: str | None = None
    timeout_default_seconds: int | None = Field(default=None, ge=1, le=28 * 86400)
    module_toggles: dict[str, bool] | None = None
    ignored_channel_ids: list[str] | None = None
    ignored_role_ids: list[str] | None = None


class ThemePatch(BaseModel):
    preset: str
    accent: str | None = None
    background: str | None = None
    surface: str | None = None
    text: str | None = None
    radius: str | None = None
    footer: str | None = None
    author_name: str | None = None
    logo_url: str | None = None
    embed_templates: dict[str, dict[str, str]] | None = None


class RuleBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: AutomodRuleType
    action: AutomodAction
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class RulePatch(BaseModel):
    name: str | None = None
    action: AutomodAction | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class StaffBody(BaseModel):
    role_id: str
    can_warn: bool = True
    can_timeout: bool = True
    can_kick: bool = True
    can_ban: bool = True


class NoteBody(BaseModel):
    target_id: str
    body: str = Field(min_length=1, max_length=2000)


class ReportPatch(BaseModel):
    status: ReportStatus


class TwitchAlertBody(BaseModel):
    login: str = Field(min_length=1, max_length=80)
    discord_channel_id: str


@router.get("/api/guilds/{guild_id}")
async def guild_detail(guild_id: str, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        guild = await session.get(Guild, parsed)
        config = await session.get(GuildConfig, parsed)
        theme = await session.get(GuildTheme, parsed)
        if guild is None or config is None or theme is None:
            raise HTTPException(status_code=404, detail="Server not found")

        async def _count(statement) -> int:
            return int(await session.scalar(statement) or 0)

        setup = {
            "automod_rules": await _count(
                select(func.count())
                .select_from(AutomodRule)
                .where(AutomodRule.guild_id == parsed, AutomodRule.enabled.is_(True))
            ),
            "staff_roles": await _count(
                select(func.count()).select_from(StaffRole).where(StaffRole.guild_id == parsed)
            ),
            "twitch_alerts": await _count(
                select(func.count()).select_from(TwitchAlert).where(TwitchAlert.guild_id == parsed)
            ),
            "open_reports": await _count(
                select(func.count())
                .select_from(Report)
                .where(Report.guild_id == parsed, Report.status.in_(("open", "claimed")))
            ),
            "open_tickets": await _count(
                select(func.count())
                .select_from(Ticket)
                .where(Ticket.guild_id == parsed, Ticket.status != "closed")
            ),
        }
        return {
            "id": str(guild.id),
            "name": guild.name,
            "config": _config_out(config),
            "theme": _theme_out(theme),
            "setup": setup,
            "actor": str(session_data["user_id"]),
        }


@router.patch("/api/guilds/{guild_id}/config")
async def patch_config(guild_id: str, body: ConfigPatch, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    if body.timezone:
        try:
            ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=422, detail="Unknown timezone") from exc
    factory = get_session_factory()
    async with factory() as session:
        config = await session.get(GuildConfig, parsed)
        if config is None:
            raise HTTPException(status_code=404, detail="Server not found")
        if body.locale is not None:
            config.locale = body.locale[:16]
        if body.timezone is not None:
            config.timezone = body.timezone
        if body.log_channel_id is not None:
            config.log_channel_id = _parse_snow(body.log_channel_id, "log_channel_id")
        if body.ticket_category_id is not None:
            config.ticket_category_id = _parse_snow(body.ticket_category_id, "ticket_category_id")
        if body.timeout_default_seconds is not None:
            config.timeout_default_seconds = body.timeout_default_seconds
        if body.module_toggles is not None:
            allowed = {"cases", "automod", "lockdown", "reports", "notes", "tickets"}
            config.module_toggles = {
                key: bool(value) for key, value in body.module_toggles.items() if key in allowed
            }
        if body.ignored_channel_ids is not None:
            config.ignored_channel_ids = [
                str(_parse_snow(item, "ignored_channel_ids")) for item in body.ignored_channel_ids
            ]
        if body.ignored_role_ids is not None:
            config.ignored_role_ids = [
                str(_parse_snow(item, "ignored_role_ids")) for item in body.ignored_role_ids
            ]
        config.updated_at = datetime.now(timezone.utc)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="config.update",
            source=AuditSource.DASHBOARD,
        )
        await notify_guild(session, parsed)
        await session.commit()
        return _config_out(config)


def _clean_templates(templates: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    cleaned: dict[str, dict[str, str]] = {}
    for key, block in templates.items():
        if key not in EMBED_TEMPLATE_KEYS:
            raise HTTPException(status_code=422, detail=f"Unknown template {key}")
        title = str(block.get("title", ""))[:256]
        description = str(block.get("description", ""))[:500]
        for chunk in (title, description):
            for match in re.findall(r"\{[a-z_]+\}", chunk):
                if match not in PLACEHOLDERS:
                    raise HTTPException(status_code=422, detail=f"Unknown placeholder {match}")
        cleaned[key] = {"title": title, "description": description}
    return cleaned


@router.put("/api/guilds/{guild_id}/theme")
async def put_theme(guild_id: str, body: ThemePatch, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    preset_name = body.preset.strip().lower()
    if preset_name != "custom" and preset_name not in PRESETS:
        raise HTTPException(status_code=422, detail="Unknown preset")
    factory = get_session_factory()
    async with factory() as session:
        theme = await session.get(GuildTheme, parsed)
        if theme is None:
            raise HTTPException(status_code=404, detail="Server not found")
        if preset_name != "custom":
            apply_preset(theme, preset_name)
        else:
            theme.preset = "custom"
        if body.accent:
            theme.accent = _check_hex(body.accent, "accent")
        if body.background:
            theme.background = _check_hex(body.background, "background")
        if body.surface:
            theme.surface = _check_hex(body.surface, "surface")
        if body.text:
            theme.text = _check_hex(body.text, "text")
        if body.radius is not None:
            if len(body.radius) > 16:
                raise HTTPException(status_code=422, detail="radius is too long")
            theme.radius = body.radius
        if body.footer is not None:
            theme.footer = body.footer[:2048]
        if body.author_name is not None:
            theme.author_name = body.author_name[:256]
        if body.logo_url is not None:
            theme.logo_url = body.logo_url or None
        if body.embed_templates is not None:
            theme.embed_templates = _clean_templates(body.embed_templates)
        theme.updated_at = datetime.now(timezone.utc)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="theme.update",
            source=AuditSource.DASHBOARD,
            payload={"preset": theme.preset},
        )
        await notify_guild(session, parsed)
        await session.commit()
        return _theme_out(theme)


@router.get("/api/guilds/{guild_id}/cases")
async def list_cases(
    guild_id: str,
    request: Request,
    target_id: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    await _require_guild(request, parsed)
    target = _parse_snow(target_id, "target_id") if target_id else None
    needle = (q or "").strip().replace("%", "").replace("_", "")
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Case).where(Case.guild_id == parsed)
        if target is not None:
            stmt = stmt.where(Case.target_id == target)
        if needle:
            like = f"%{needle}%"
            stmt = stmt.where(
                or_(
                    Case.reason.ilike(like),
                    cast(Case.type, String).ilike(like),
                    cast(Case.case_number, String).like(like),
                    cast(Case.target_id, String).like(like),
                    cast(Case.moderator_id, String).like(like),
                )
            )
        rows = list((await session.scalars(stmt.order_by(Case.case_number.desc()).limit(100))).all())
        return [
            {
                "id": str(row.id),
                "case_number": row.case_number,
                "type": row.type,
                "target_id": str(row.target_id),
                "moderator_id": _snow(row.moderator_id),
                "reason": row.reason,
                "evidence_url": row.evidence_url,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "reversed_at": row.reversed_at.isoformat() if row.reversed_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]


@router.get("/api/guilds/{guild_id}/reports")
async def list_reports(guild_id: str, request: Request) -> list[dict[str, Any]]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        rows = await reports_for_guild(session, parsed, limit=100)
        return [
            {
                "id": str(row.id),
                "reporter_id": str(row.reporter_id),
                "target_id": str(row.target_id),
                "reason": row.reason,
                "status": row.status,
                "jump_url": row.jump_url,
                "claimed_by": _snow(row.claimed_by),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]


@router.patch("/api/guilds/{guild_id}/reports/{report_id}")
async def patch_report(guild_id: str, report_id: str, body: ReportPatch, request: Request) -> dict[str, str]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid report id") from exc
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(Report, report_uuid)
        if row is None or row.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Report not found")
        row.status = body.status
        if body.status == ReportStatus.CLAIMED:
            row.claimed_by = int(session_data["user_id"])
        if body.status in {ReportStatus.RESOLVED, ReportStatus.REJECTED}:
            row.resolved_at = datetime.now(timezone.utc)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action=f"report.{body.status}",
            source=AuditSource.DASHBOARD,
            target_type="report",
            target_id=str(row.id),
        )
        await session.commit()
    return {"id": report_id, "status": body.status}


@router.get("/api/guilds/{guild_id}/notes")
async def list_notes(guild_id: str, target_id: str, request: Request) -> list[dict[str, Any]]:
    parsed = _parse_snow(guild_id, "guild_id")
    target = _parse_snow(target_id, "target_id")
    assert parsed is not None and target is not None
    await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        rows = await notes_for_target(session, parsed, target)
        return [
            {
                "id": str(row.id),
                "target_id": str(row.target_id),
                "author_id": str(row.author_id),
                "body": row.body,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]


@router.post("/api/guilds/{guild_id}/notes")
async def create_note(guild_id: str, body: NoteBody, request: Request) -> dict[str, str]:
    parsed = _parse_snow(guild_id, "guild_id")
    target = _parse_snow(body.target_id, "target_id")
    assert parsed is not None and target is not None
    session_data = await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        note = MemberNote(
            guild_id=parsed,
            target_id=target,
            author_id=int(session_data["user_id"]),
            body=body.body.strip(),
        )
        session.add(note)
        await session.flush()
        note_id = str(note.id)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="note.add",
            source=AuditSource.DASHBOARD,
            target_type="user",
            target_id=str(target),
        )
        await session.commit()
    return {"id": note_id}


@router.delete("/api/guilds/{guild_id}/notes/{note_id}", status_code=204)
async def delete_note(guild_id: str, note_id: str, request: Request) -> None:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    note_uuid = _parse_uuid(note_id, "note_id")
    factory = get_session_factory()
    async with factory() as session:
        note = await session.get(MemberNote, note_uuid)
        if note is None or note.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Note not found")
        await session.delete(note)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="note.delete",
            source=AuditSource.DASHBOARD,
            target_type="note",
            target_id=note_id,
        )
        await session.commit()


@router.delete("/api/guilds/{guild_id}/cases/{case_id}", status_code=204)
async def delete_case(guild_id: str, case_id: str, request: Request) -> None:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    case_uuid = _parse_uuid(case_id, "case_id")
    factory = get_session_factory()
    async with factory() as session:
        case = await session.get(Case, case_uuid)
        if case is None or case.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Case not found")
        if case.log_channel_id and case.log_message_id:
            session.add(
                ScheduledAction(
                    guild_id=parsed,
                    case_id=None,
                    action="delete_message",
                    payload={"channel_id": case.log_channel_id, "message_id": case.log_message_id},
                    run_at=datetime.now(timezone.utc),
                )
            )
        await session.delete(case)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="case.delete",
            source=AuditSource.DASHBOARD,
            target_type="case",
            target_id=case_id,
        )
        await session.commit()


@router.delete("/api/guilds/{guild_id}/reports/{report_id}", status_code=204)
async def delete_report(guild_id: str, report_id: str, request: Request) -> None:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    report_uuid = _parse_uuid(report_id, "report_id")
    factory = get_session_factory()
    async with factory() as session:
        report = await session.get(Report, report_uuid)
        if report is None or report.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Report not found")
        await session.delete(report)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="report.delete",
            source=AuditSource.DASHBOARD,
            target_type="report",
            target_id=report_id,
        )
        await session.commit()


class TicketReply(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def _ticket_out(row: Ticket) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "number": row.number,
        "opener_id": str(row.opener_id),
        "subject": row.subject,
        "status": row.status,
        "claimed_by": _snow(row.claimed_by),
        "channel_id": _snow(row.channel_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }


@router.get("/api/guilds/{guild_id}/tickets")
async def list_tickets(guild_id: str, request: Request) -> list[dict[str, Any]]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(Ticket).where(Ticket.guild_id == parsed).order_by(Ticket.number.desc()).limit(50)
                )
            ).all()
        )
        return [_ticket_out(row) for row in rows]


@router.post("/api/guilds/{guild_id}/tickets/{ticket_id}/claim")
async def claim_ticket(guild_id: str, ticket_id: str, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    ticket_uuid = _parse_uuid(ticket_id, "ticket_id")
    factory = get_session_factory()
    async with factory() as session:
        ticket = await session.get(Ticket, ticket_uuid)
        if ticket is None or ticket.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Ticket not found")
        if ticket.status == "closed":
            raise HTTPException(status_code=409, detail="That ticket is closed")
        actor = int(session_data["user_id"])
        ticket.status = "claimed"
        ticket.claimed_by = actor
        session.add(TicketMessage(ticket_id=ticket.id, author_id=actor, body="Claimed this ticket."))
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=actor,
            action="ticket.claim",
            source=AuditSource.DASHBOARD,
            target_type="ticket",
            target_id=ticket_id,
        )
        await session.commit()
        await session.refresh(ticket)
        return _ticket_out(ticket)


@router.post("/api/guilds/{guild_id}/tickets/{ticket_id}/close")
async def close_ticket(guild_id: str, ticket_id: str, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    ticket_uuid = _parse_uuid(ticket_id, "ticket_id")
    factory = get_session_factory()
    async with factory() as session:
        ticket = await session.get(Ticket, ticket_uuid)
        if ticket is None or ticket.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Ticket not found")
        actor = int(session_data["user_id"])
        ticket.status = "closed"
        ticket.closed_at = datetime.now(timezone.utc)
        session.add(TicketMessage(ticket_id=ticket.id, author_id=actor, body="Closed this ticket."))
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=actor,
            action="ticket.close",
            source=AuditSource.DASHBOARD,
            target_type="ticket",
            target_id=ticket_id,
        )
        await session.commit()
        await session.refresh(ticket)
        return _ticket_out(ticket)


@router.post("/api/guilds/{guild_id}/tickets/{ticket_id}/messages", status_code=204)
async def reply_ticket(guild_id: str, ticket_id: str, body: TicketReply, request: Request) -> None:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    ticket_uuid = _parse_uuid(ticket_id, "ticket_id")
    factory = get_session_factory()
    async with factory() as session:
        ticket = await session.get(Ticket, ticket_uuid)
        if ticket is None or ticket.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Ticket not found")
        if ticket.status == "closed":
            raise HTTPException(status_code=409, detail="That ticket is closed")
        session.add(
            TicketMessage(
                ticket_id=ticket.id,
                author_id=int(session_data["user_id"]),
                body=body.body.strip(),
            )
        )
        await session.commit()


def _rule_payload(row: AutomodRule) -> dict[str, Any]:
    config = dict(row.config or {})
    return {
        "id": str(row.id),
        "name": row.name,
        "type": row.type,
        "action": row.action,
        "enabled": row.enabled,
        "config": config,
        "summary": describe_rule(row.type, row.action, config),
    }


def _clean_rule(rule_type: str, action: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    try:
        return normalize_config(rule_type, action, raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/guilds/{guild_id}/automod")
async def list_rules(guild_id: str, request: Request) -> list[dict[str, Any]]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(AutomodRule).where(AutomodRule.guild_id == parsed).order_by(AutomodRule.created_at)
                )
            ).all()
        )
        return [_rule_payload(row) for row in rows]


@router.post("/api/guilds/{guild_id}/automod")
async def create_rule(guild_id: str, body: RuleBody, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        row = AutomodRule(
            guild_id=parsed,
            name=body.name.strip(),
            type=body.type,
            action=body.action,
            enabled=body.enabled,
            config=_clean_rule(body.type, body.action, body.config),
        )
        session.add(row)
        await session.flush()
        payload = _rule_payload(row)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="automod.create",
            source=AuditSource.DASHBOARD,
            target_type="automod_rule",
            target_id=str(row.id),
        )
        await notify_guild(session, parsed)
        await session.commit()
    return payload


@router.patch("/api/guilds/{guild_id}/automod/{rule_id}")
async def patch_rule(guild_id: str, rule_id: str, body: RulePatch, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid rule id") from exc
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(AutomodRule, rule_uuid)
        if row is None or row.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Rule not found")
        if body.name is not None:
            cleaned_name = body.name.strip()[:100]
            if not cleaned_name:
                raise HTTPException(status_code=422, detail="Give the rule a name.")
            row.name = cleaned_name
        if body.enabled is not None:
            row.enabled = body.enabled
        if body.action is not None or body.config is not None:
            action = body.action or row.action
            raw = body.config if body.config is not None else dict(row.config or {})
            row.action = action
            row.config = _clean_rule(row.type, action, raw)
        row.updated_at = datetime.now(timezone.utc)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="automod.update",
            source=AuditSource.DASHBOARD,
            target_id=str(row.id),
        )
        await notify_guild(session, parsed)
        await session.commit()
        return _rule_payload(row)


@router.delete("/api/guilds/{guild_id}/automod/{rule_id}")
async def delete_rule(guild_id: str, rule_id: str, request: Request) -> Response:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid rule id") from exc
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(AutomodRule, rule_uuid)
        if row is None or row.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Rule not found")
        await session.delete(row)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="automod.delete",
            source=AuditSource.DASHBOARD,
            target_id=rule_id,
        )
        await notify_guild(session, parsed)
        await session.commit()
    return Response(status_code=204)


@router.get("/api/guilds/{guild_id}/twitch")
async def list_twitch(guild_id: str, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(TwitchAlert, TwitchLiveState.live)
                .outerjoin(TwitchLiveState, TwitchLiveState.broadcaster_id == TwitchAlert.twitch_user_id)
                .where(TwitchAlert.guild_id == parsed)
                .order_by(TwitchAlert.twitch_login)
            )
        ).all()
    alerts = [
        {
            "id": str(alert.id),
            "login": alert.twitch_login,
            "channel_id": str(alert.discord_channel_id),
            "enabled": alert.enabled,
            "live": bool(live),
        }
        for alert, live in rows
    ]
    return {"configured": twitch_configured(), "alerts": alerts}


@router.post("/api/guilds/{guild_id}/twitch")
async def add_twitch(guild_id: str, body: TwitchAlertBody, request: Request) -> dict[str, Any]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    await _require_guild(request, parsed)
    if not twitch_configured():
        raise HTTPException(status_code=424, detail="Twitch is not configured on this bot.")
    try:
        login = normalize_login(body.login)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    channel_id = _parse_snow(body.discord_channel_id, "discord_channel_id")
    if channel_id is None:
        raise HTTPException(status_code=422, detail="Choose a Discord channel.")
    try:
        profile = await lookup_user(login)
    except TwitchError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    factory = get_session_factory()
    async with factory() as session:
        row = await session.scalar(
            select(TwitchAlert).where(
                TwitchAlert.guild_id == parsed,
                TwitchAlert.twitch_user_id == profile["id"],
            )
        )
        if row is None:
            row = TwitchAlert(
                guild_id=parsed,
                discord_channel_id=channel_id,
                twitch_login=profile["login"],
                twitch_user_id=profile["id"],
                enabled=True,
            )
            session.add(row)
        else:
            row.discord_channel_id = channel_id
            row.twitch_login = profile["login"]
            row.enabled = True
        await session.flush()
        alert_id = str(row.id)
        await session.commit()
    note = await ensure_eventsub(profile["id"])
    return {
        "id": alert_id,
        "login": profile["login"],
        "channel_id": str(channel_id),
        "enabled": True,
        "live": False,
        "note": note,
    }


@router.delete("/api/guilds/{guild_id}/twitch/{alert_id}", status_code=204)
async def delete_twitch(guild_id: str, alert_id: str, request: Request) -> Response:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    await _require_guild(request, parsed)
    alert_uuid = _parse_uuid(alert_id, "alert_id")
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(TwitchAlert, alert_uuid)
        if row is None or row.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Twitch alert not found")
        broadcaster_id = row.twitch_user_id
        await session.delete(row)
        await session.flush()
        remaining = await session.scalar(
            select(func.count()).select_from(TwitchAlert).where(TwitchAlert.twitch_user_id == broadcaster_id)
        )
        await session.commit()
    if not remaining and twitch_configured():
        await delete_eventsub(broadcaster_id)
    return Response(status_code=204)


@router.get("/api/guilds/{guild_id}/staff")
async def list_staff(guild_id: str, request: Request) -> list[dict[str, Any]]:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        rows = list((await session.scalars(select(StaffRole).where(StaffRole.guild_id == parsed))).all())
        return [
            {
                "id": str(row.id),
                "role_id": str(row.role_id),
                "can_warn": row.can_warn,
                "can_timeout": row.can_timeout,
                "can_kick": row.can_kick,
                "can_ban": row.can_ban,
            }
            for row in rows
        ]


@router.post("/api/guilds/{guild_id}/staff")
async def add_staff(guild_id: str, body: StaffBody, request: Request) -> dict[str, str]:
    parsed = _parse_snow(guild_id, "guild_id")
    role_id = _parse_snow(body.role_id, "role_id")
    assert parsed is not None and role_id is not None
    session_data = await _require_guild(request, parsed)
    factory = get_session_factory()
    async with factory() as session:
        await upsert_staff_role(
            session,
            parsed,
            role_id,
            can_warn=body.can_warn,
            can_timeout=body.can_timeout,
            can_kick=body.can_kick,
            can_ban=body.can_ban,
        )
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="staff.upsert",
            source=AuditSource.DASHBOARD,
            target_type="role",
            target_id=str(role_id),
        )
        await notify_guild(session, parsed)
        await session.commit()
    return {"role_id": str(role_id)}


@router.delete("/api/guilds/{guild_id}/staff/{staff_id}")
async def delete_staff(guild_id: str, staff_id: str, request: Request) -> Response:
    parsed = _parse_snow(guild_id, "guild_id")
    assert parsed is not None
    session_data = await _require_guild(request, parsed)
    try:
        staff_uuid = uuid.UUID(staff_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid staff id") from exc
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(StaffRole, staff_uuid)
        if row is None or row.guild_id != parsed:
            raise HTTPException(status_code=404, detail="Staff role not found")
        await session.delete(row)
        await add_audit(
            session,
            guild_id=parsed,
            actor_id=int(session_data["user_id"]),
            action="staff.delete",
            source=AuditSource.DASHBOARD,
            target_id=staff_id,
        )
        await notify_guild(session, parsed)
        await session.commit()
    return Response(status_code=204)
