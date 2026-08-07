"""OIDC relying party — /auth/* routes (auth-track Step 4; design §4.2).

Authlib runs the authorization-code + PKCE flow against the configured
issuer (authentik on Josh's instance, but any OIDC provider works). All
tokens stay server-side: the browser only ever gets the opaque session
cookie. Starlette's SessionMiddleware (mounted in app.py with a per-boot
secret and a short max_age) holds nothing but the handshake state/nonce
and the post-login destination.

Config resolution follows the house rule (file > admin UI/DB > env):

    auth:
      mode: oidc
      issuer: https://auth.example.com/application/o/tarot/
      client_id: tarot
      client_secret_env: TAROT_OIDC_CLIENT_SECRET   # or client_secret:
      auto_provision: true      # JIT user rows (default on)
      session_days: 90

Identity = the `preferred_username` claim run through the EXACT historical
sanitizer (auth.sanitize_identity) — byte-for-byte continuity with every
owner string the header era wrote to the DB and disk.
"""

import os
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from tarot import auth, config as cfgfile, sessions, users

router = APIRouter()

_oauth = None
_oauth_key: tuple | None = None


def oidc_config() -> dict | None:
    """Resolved issuer/client_id/client_secret, or None when not configured."""
    from tarot import crypto, db

    issuer = str(
        cfgfile.get("auth", "issuer")
        or db.get_setting("auth_issuer")
        or os.environ.get("TAROT_OIDC_ISSUER", "")
    ).strip().rstrip("/")
    client_id = str(
        cfgfile.get("auth", "client_id")
        or db.get_setting("auth_client_id")
        or os.environ.get("TAROT_OIDC_CLIENT_ID", "")
    ).strip()
    secret = cfgfile.auth_client_secret()
    if secret is None:
        stored = db.get_setting("auth_client_secret")
        secret = crypto.decrypt(stored) if stored else os.environ.get(
            "TAROT_OIDC_CLIENT_SECRET", "")
    if not issuer or not client_id:
        return None
    return {"issuer": issuer, "client_id": client_id, "client_secret": secret or ""}


def _client():
    """The Authlib client, rebuilt whenever the resolved config changes."""
    global _oauth, _oauth_key
    from authlib.integrations.starlette_client import OAuth

    cfg = oidc_config()
    if cfg is None:
        raise HTTPException(404, "OIDC sign-in is not configured")
    key = (cfg["issuer"], cfg["client_id"], cfg["client_secret"])
    if _oauth is None or _oauth_key != key:
        oauth = OAuth()
        oauth.register(
            "idp",
            client_id=cfg["client_id"],
            client_secret=cfg["client_secret"],
            server_metadata_url=f"{cfg['issuer']}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email",
                           "code_challenge_method": "S256"},
        )
        _oauth, _oauth_key = oauth, key
    return _oauth.idp


def _safe_next(next_url: str | None) -> str:
    """Same-origin paths only — no open redirect through the login flow."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


@router.get("/auth/login")
async def login(request: Request, next: str | None = None):
    client = _client()
    request.session["next"] = _safe_next(next)
    redirect_uri = str(request.url.replace(path="/auth/callback", query=""))
    try:
        return await client.authorize_redirect(request, redirect_uri)
    except Exception as e:
        raise HTTPException(502, f"sign-in provider unreachable: {e}")


_RETRY_PAGE = """<!doctype html><meta charset="utf-8"><title>Sign-in problem</title>
<body style="font-family:system-ui;max-width:30rem;margin:4rem auto;text-align:center">
<h1>{title}</h1><p>{message}</p><p><a href="/auth/login">Try signing in again</a></p></body>"""


@router.get("/auth/callback")
async def callback(request: Request):
    client = _client()
    try:
        token = await client.authorize_access_token(request)
    except Exception:
        return HTMLResponse(_RETRY_PAGE.format(
            title="Sign-in expired", message="The sign-in attempt expired or was invalid."),
            status_code=400)
    claims = token.get("userinfo") or {}
    raw = str(claims.get("preferred_username") or claims.get("email") or "").strip()
    if not raw:
        return HTMLResponse(_RETRY_PAGE.format(
            title="Sign-in failed", message="The identity provider sent no usable username."),
            status_code=403)
    user = auth.sanitize_identity(raw.lower())
    if not auth.auto_provision() and users.get(user) is None:
        return HTMLResponse(_RETRY_PAGE.format(
            title="Account not provisioned",
            message="Your sign-in worked, but this account hasn't been set up here yet — ask your admin."),
            status_code=403)
    # Synchronous on purpose: the session row references users(username).
    users.touch_sync(user, auth.display_name_from(raw))
    days = auth.session_days()
    cookie = sessions.create(user, id_token=token.get("id_token"), session_days=days)
    resp = RedirectResponse(request.session.pop("next", "/") or "/", status_code=303)
    resp.set_cookie(
        auth.COOKIE_NAME, cookie,
        max_age=days * 86400, httponly=True, samesite="lax",
        secure=request.url.scheme == "https", path="/",
    )
    return resp


@router.post("/auth/logout")
async def logout(request: Request):
    """Destroy the app session and hand the SPA the IdP's end-session URL
    (best effort — the browser navigates there to also end the SSO session)."""
    token = request.cookies.get(auth.COOKIE_NAME, "")
    end_url = None
    if token:
        id_token = sessions.id_token_for(token)
        sessions.destroy(token)
        try:
            client = _client()
            meta = await client.load_server_metadata()
            end = meta.get("end_session_endpoint")
            if end:
                base = str(request.url.replace(path="/", query=""))
                end_url = f"{end}?post_logout_redirect_uri={base}"
                if id_token:
                    end_url += f"&id_token_hint={id_token}"
        except Exception:
            end_url = None
    resp = JSONResponse({"logout_url": end_url or "/"})
    resp.delete_cookie(auth.COOKIE_NAME, path="/")
    return resp


# --- first-admin bootstrap (design §4.3) ------------------------------------
# Regenerated each boot while no active admin exists; printed to the log;
# single-use. Promotion applies to the CURRENTLY SIGNED-IN user.

_setup_token: str | None = None
_setup_token_born: float = 0


def ensure_setup_token() -> None:
    global _setup_token, _setup_token_born
    import secrets

    if users.active_admin_exists():
        _setup_token = None
        return
    if _setup_token is None:
        _setup_token = secrets.token_urlsafe(24)
        _setup_token_born = time.time()
        print(f"TAROT SETUP: no admin exists — sign in, then visit /auth/setup "
              f"and enter: {_setup_token}", flush=True)


def consume_setup_token(supplied: str, user: str) -> bool:
    global _setup_token
    if not _setup_token or not supplied or supplied != _setup_token:
        return False
    users.flush_touches()
    users.set_admin(user, True)
    _setup_token = None
    return True
