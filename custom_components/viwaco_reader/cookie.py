"""Normalize a manually copied HTTP Cookie request header (not Set-Cookie).

Keep this pure-Python so it can be unit tested without Home Assistant.
"""

import re

_COOKIE_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class CookieFormatError(ValueError):
    """A pasted Cookie is not in request-header format."""


def normalize_cookie(raw: str) -> str:
    """Accept either 'a=1; b=2' or 'Cookie: a=1; b=2'.

    Never parse or include Set-Cookie attributes; never disclose the value.
    """
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 8192:
        raise CookieFormatError("Cookie header is missing or too large")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise CookieFormatError("Cookie header contains control characters")
    value = raw.strip()
    if value[:7].lower() == "cookie:":
        value = value[7:].strip()
    if value.lower().startswith("set-cookie:"):
        raise CookieFormatError("Copy Request Headers > Cookie, not Set-Cookie")

    pairs = []
    for field in value.split(";"):
        field = field.strip()
        if not field:
            continue
        if "=" not in field:
            raise CookieFormatError("Cookie must contain name=value pairs")
        name, val = field.split("=", 1)
        name, val = name.strip(), val.strip()
        if not _COOKIE_NAME.fullmatch(name) or not val:
            raise CookieFormatError("Invalid Cookie name or value")
        if any(ord(ch) > 126 for ch in val):
            raise CookieFormatError("Invalid Cookie character")
        pairs.append(f"{name}={val}")
    if not pairs:
        raise CookieFormatError("Cookie header has no cookies")
    return "; ".join(pairs)
