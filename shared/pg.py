"""Postgres URL helpers that stay independent of the driver imports."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def asyncpg_connect_args(database_url: str) -> tuple[str, dict[str, str]]:
    """Return a DSN and connect kwargs.

    SQLAlchemy accepts ``?ssl=require`` and passes it as the asyncpg ``ssl``
    argument. A raw DSN leaves that name in the query string, and Postgres
    then rejects it as a server parameter.
    """
    raw = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    ssl_value = query.pop("sslmode", None)
    if ssl_value is None:
        ssl_value = query.pop("ssl", None)
    else:
        query.pop("ssl", None)
    dsn = urlunsplit(parts._replace(query=urlencode(query)))
    kwargs: dict[str, str] = {}
    if ssl_value:
        kwargs["ssl"] = ssl_value
    return dsn, kwargs
