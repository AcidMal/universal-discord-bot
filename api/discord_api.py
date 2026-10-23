from __future__ import annotations

from typing import Any

import httpx

API = "https://discord.com/api/v10"
MANAGE_GUILD = 1 << 5
ADMINISTRATOR = 1 << 3


async def discord_request(
    method: str,
    path: str,
    *,
    token: str,
    bot: bool = False,
    data: dict | None = None,
    form: dict | None = None,
) -> Any:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"{'Bot' if bot else 'Bearer'} {token}"
    kwargs: dict = {}
    if data is not None:
        kwargs["json"] = data
    if form is not None:
        kwargs["data"] = form
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(method, f"{API}{path}", headers=headers, **kwargs)
    if response.status_code == 401:
        return None
    if response.status_code >= 400:
        raise RuntimeError(f"Discord {response.status_code} on {path}: {response.text[:300]}")
    if not response.content:
        return None
    return response.json()


def can_manage(permissions: int) -> bool:
    return bool(permissions & ADMINISTRATOR or permissions & MANAGE_GUILD)
