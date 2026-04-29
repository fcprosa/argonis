"""Normalize secret values loaded from .env / process environment."""

from __future__ import annotations


def sanitize_env_secret(value: str | None) -> str:
    """Strip BOM/whitespace/CRLF, unwrap one or more layers of matching outer quotes.

    python-dotenv and editors sometimes leave values wrapped in ``"..."`` or
    with trailing ``\\r``; Pydantic passes the string through unchanged unless
    we normalize.
    """
    if value is None:
        return ""
    v = value.replace("\r", "").replace("\n", "")
    v = v.strip()
    if v.startswith("\ufeff"):
        v = v.lstrip("\ufeff").strip()
    while len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
    return v
