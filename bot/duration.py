from __future__ import annotations

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(raw: str | None, *, bare_unit: str = "m") -> int | None:
    """Parse `10`, `10m`, `2h`, `1d`, or `30s`. A bare number uses `bare_unit`."""
    if raw is None:
        return None
    text = raw.strip().lower()
    if not text:
        return None
    if text.isdigit():
        return int(text) * _UNITS[bare_unit]
    unit = text[-1]
    amount = text[:-1]
    if unit not in _UNITS or not amount.isdigit() or amount == "":
        raise ValueError("Use a duration like 10m, 2h, 1d, or 30s")
    seconds = int(amount) * _UNITS[unit]
    if seconds <= 0:
        raise ValueError("Duration must be greater than zero")
    if seconds > 28 * 86400:
        raise ValueError("Duration cannot be longer than 28 days")
    return seconds
