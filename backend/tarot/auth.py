"""Identity policy — the mode arbiter (auth-track Step 4; design §4.3).

Three modes, chosen by the `auth:` config section (file > DB/env):

- **legacy** (no `auth:` section at all): exactly the pre-OIDC behaviour —
  the proxy header is trusted from anywhere, an absent header falls back to
  the shared `local` user. Existing single-user and forward-auth installs
  keep working untouched.
- **header** (`auth.mode: header`): hardened proxy auth — the header is
  honored only when trusted_header.enabled AND the immediate client IP is
  inside the trusted_header.proxies CIDR allowlist (no default). No
  anonymous fallback.
- **oidc** (`auth.mode: oidc`): the app runs its own OIDC login (oidc.py);
  identity comes from the session cookie. The hardened header path may be
  enabled alongside as an alternative surface.

This module stays free of top-level database imports (sessions/users are
resolved by the request dependency in api/app.py); it owns the pure policy:
mode selection, header trust, sanitization, and the cookie contract.

The session cookie is a plain host-only cookie (NOT `__Host-` — that prefix
requires Secure, and LAN access is plain http). Host-only already keeps it
off sibling subdomains; `Secure` is added automatically on https requests.
"""

import ipaddress
import os
import re

from fastapi import Request

from tarot import config as cfgfile

AUTH_HEADER = os.environ.get("TAROT_AUTH_HEADER", "x-authentik-username")
FALLBACK_USER = os.environ.get("TAROT_FALLBACK_USER", "local")
COOKIE_NAME = "tarot_session"

# Where the logout button sends the browser in legacy mode. authentik's
# forward-auth outpost serves its sign-out endpoint under the protected
# domain by default. In oidc mode the SPA calls POST /auth/logout instead.
LOGOUT_URL = os.environ.get(
    "TAROT_LOGOUT_URL", "/outpost.goauthentik.io/sign_out"
)

# Env-seeded admins: consulted only when creating a user row (users.touch)
# and by the _m9 migration sweep. Request-time admin checks read the
# registry (users.is_admin) — flip flags in-app, not here.
ADMIN_USERS = {
    u.strip().lower()
    for u in os.environ.get("TAROT_ADMIN_USERS", FALLBACK_USER).split(",")
    if u.strip()
}


def env_is_admin(user: str) -> bool:
    return user in ADMIN_USERS


LEGACY, HEADER, OIDC = "legacy", "header", "oidc"


def mode() -> str:
    """Resolved auth mode. Config file wins; DB setting next; env last; an
    absent/unknown value means legacy (full back-compat)."""
    from tarot import db

    m = cfgfile.get("auth", "mode")
    if m is None:
        m = db.get_setting("auth_mode") or os.environ.get("TAROT_AUTH_MODE", "")
    m = str(m).strip().lower()
    return m if m in (HEADER, OIDC) else LEGACY


def session_days() -> int:
    try:
        return max(1, int(cfgfile.get("auth", "session_days", 90)))
    except (TypeError, ValueError):
        return 90


def auto_provision() -> bool:
    """JIT user provisioning (default ON — the IdP's access policy is the
    real gate; turn off to require pre-created users)."""
    v = cfgfile.get("auth", "auto_provision")
    if v is None:
        from tarot import db

        v = db.get_setting("auth_auto_provision") or None
    if v is None:
        return True
    return str(v).strip().lower() not in ("false", "0", "no", "off")


def _trusted_header_cfg() -> dict:
    v = cfgfile.get("auth", "trusted_header")
    return v if isinstance(v, dict) else {}


def header_trusted(request: Request) -> bool:
    """May this request's proxy header be believed?

    legacy mode: always (the historical contract).
    header/oidc: only when explicitly enabled AND the immediate peer is in
    the CIDR allowlist — an empty list trusts no one."""
    if mode() == LEGACY:
        return True
    th = _trusted_header_cfg()
    if not th.get("enabled"):
        return False
    client = request.client.host if request.client else ""
    if not client:
        return False
    try:
        ip = ipaddress.ip_address(client)
    except ValueError:
        return False
    for cidr in th.get("proxies") or []:
        try:
            if ip in ipaddress.ip_network(str(cidr), strict=False):
                return True
        except ValueError:
            continue
    return False


_SAFE = re.compile(r"[^a-z0-9._-]")


def sanitize_identity(raw: str) -> str:
    """The stable storage identity for a raw IdP/header username — the exact
    historical transform, byte-for-byte: every owner string in the DB and on
    disk was produced by this."""
    return _SAFE.sub("_", raw.lower())[:64]


def _raw_identity(request: Request) -> str:
    return request.headers.get(AUTH_HEADER, "").strip()


def current_user(request: Request) -> str:
    """Header-derived storage identity (legacy/header modes)."""
    raw = _raw_identity(request).lower()
    if not raw:
        return FALLBACK_USER
    return sanitize_identity(raw)


def is_authenticated(request: Request) -> bool:
    """True when a real identity backs this request (header supplied, or a
    session cookie is present — the dependency has already validated it by
    the time anyone asks)."""
    return bool(_raw_identity(request)) or bool(request.cookies.get(COOKIE_NAME))


def display_name_from(raw: str) -> str:
    """Friendly name for a raw identity: emails collapse to their local part
    so 'someone@example.com' shows as 'someone'."""
    if not raw:
        return FALLBACK_USER
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    return raw[:64]


def display_name(request: Request) -> str:
    """Friendly name from the request header. Does not affect the storage
    identity; a self-chosen display name (user_settings override) wins over
    this everywhere names are shown."""
    return display_name_from(_raw_identity(request))
