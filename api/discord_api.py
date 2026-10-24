from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

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
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, f"{API}{path}", headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Discord could not be reached") from exc
    if response.status_code in {401, 404}:
        return None
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Discord rejected the request")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Discord sent a response that was not JSON") from exc


def can_manage(permissions: int) -> bool:
    return bool(permissions & ADMINISTRATOR or permissions & MANAGE_GUILD)
