from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from fastapi import HTTPException, Request, Response

from shared.settings import get_settings

COOKIE = "udb_session"
STATE_COOKIE = "oauth_state"
MAX_AGE = 60 * 60 * 24 * 7


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="udb-session")


def write_session(response: Response, payload: dict) -> None:
    settings = get_settings()
    token = _serializer().dumps(payload)
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.public_url.startswith("https"),
        max_age=MAX_AGE,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def read_session(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required")
    try:
        data = _serializer().loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=401, detail="Sign in required") from exc
    if not isinstance(data, dict) or "access_token" not in data:
        raise HTTPException(status_code=401, detail="Sign in required")
    return data
