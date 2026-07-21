"""Identity from reverse-proxy headers (authentik proxy provider / forward auth).

The proxy authenticates and injects a username header; we trust it. When the
header is absent (direct LAN access, dev), everyone is the 'local' user.
Only ever expose this app through the authenticating proxy if multiple users
matter to you — the header is trusted as-is.
"""

import os
import re

from fastapi import Request

AUTH_HEADER = os.environ.get("TAROT_AUTH_HEADER", "x-authentik-username")
FALLBACK_USER = os.environ.get("TAROT_FALLBACK_USER", "local")

# Where the logout button sends the browser. authentik's forward-auth outpost
# serves its sign-out endpoint under the protected domain by default.
LOGOUT_URL = os.environ.get(
    "TAROT_LOGOUT_URL", "/outpost.goauthentik.io/sign_out"
)

# Users allowed to manage instance settings (LLM connection). Defaults to the
# fallback user so single-user LAN mode is admin out of the box.
ADMIN_USERS = {
    u.strip().lower()
    for u in os.environ.get("TAROT_ADMIN_USERS", FALLBACK_USER).split(",")
    if u.strip()
}


def is_admin(user: str) -> bool:
    return user in ADMIN_USERS

_SAFE = re.compile(r"[^a-z0-9._-]")


def _raw_identity(request: Request) -> str:
    return request.headers.get(AUTH_HEADER, "").strip()


def current_user(request: Request) -> str:
    """Stable storage identity — sanitized, used for filesystem paths."""
    raw = _raw_identity(request).lower()
    if not raw:
        return FALLBACK_USER
    return _SAFE.sub("_", raw)[:64]


def is_authenticated(request: Request) -> bool:
    """True when the proxy supplied an identity (i.e. not direct LAN access)."""
    return bool(_raw_identity(request))


def display_name(request: Request) -> str:
    """Friendly name for the UI. Emails collapse to their local part so an
    identity like 'someone@example.com' shows as 'someone' rather than the
    sanitized 'someone_example.com'. Does not affect the storage identity."""
    raw = _raw_identity(request)
    if not raw:
        return FALLBACK_USER
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    return raw[:64]
