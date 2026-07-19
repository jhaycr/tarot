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

_SAFE = re.compile(r"[^a-z0-9._-]")


def current_user(request: Request) -> str:
    raw = request.headers.get(AUTH_HEADER, "").strip().lower()
    if not raw:
        return FALLBACK_USER
    return _SAFE.sub("_", raw)[:64]
