"""Safe request Cookie rotation from Set-Cookie of the *tracuu* host only.

The source host is fixed in api.py. Cookies from the separate invoice PDF
host are never merged into the authentication session.
"""

from http.cookies import Morsel
from .cookie import normalize_cookie, CookieFormatError

_HOST = "tracuu.viwaco.vn"


def merge_response_cookies(current: str, response_cookies) -> str:
    """Return request Cookie header updated from valid first-party Set-Cookie.

    Ignore unrelated domains, paths other than /, expired/deletion cookies,
    malformed entries and attributes. Never return or log Set-Cookie metadata.
    """
    old = normalize_cookie(current)
    cookies = dict(part.split("=", 1) for part in old.split("; "))
    for name, morsel in response_cookies.items():
        if not isinstance(morsel, Morsel):
            continue
        domain = (morsel["domain"] or "").lstrip(".").lower()
        path = morsel["path"] or "/"
        if domain and domain != _HOST:
            continue
        # Only cookies valid for both /Invoice.aspx and /Reading.aspx.
        if path != "/":
            continue
        if morsel["max-age"] == "0" or not morsel.value:
            cookies.pop(name, None)
            continue
        if any(ch.isspace() for ch in morsel.value):
            continue
        try:
            normalize_cookie(f"{name}={morsel.value}")
        except CookieFormatError:
            continue
        cookies[name] = morsel.value
    if not cookies:
        # An invalidated session must not erase the Cookie before HA starts reauth.
        return old
    return normalize_cookie("; ".join(f"{k}={v}" for k, v in cookies.items()))
