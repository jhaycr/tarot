import io
import json
import os
import re
import secrets
import threading
import time
import zipfile

import httpx
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from tarot import auth, bookimport, config as cfgfile, crypto, db, dedupe, importer, interpret as interp, limits, sessions, sse, tts, users
from tarot import books as books_mod
from tarot.books import BookConflict, BookForbidden, user_books_dir
from tarot.auth import (
    LOGOUT_URL,
    current_user,
    display_name,
    is_authenticated,
)
from tarot.users import is_admin
from tarot.cards import CARDS
from tarot import decks as decks_mod
from tarot.decks import (
    DeckConflict,
    DeckForbidden,
    IMAGE_EXTS,
    discover_decks,
    user_decks_dir,
)
from tarot.spreads import SPREADS, SPREADS_BY_SLUG

app = FastAPI(title="Tarotarium", docs_url="/api/docs", openapi_url="/api/openapi.json")

# OIDC handshake state (state/nonce/next) only — a per-boot secret is fine
# because the cookie lives minutes; a restart mid-login just means retrying.
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

app.add_middleware(
    SessionMiddleware, secret_key=secrets.token_hex(32),
    session_cookie="tarot_oauth", max_age=600, same_site="lax",
)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """Cross-origin write protection for cookie-auth'd requests (design
    §4.7). SameSite=Lax alone is insufficient — sibling subdomains are
    "same-site". Browsers always send Sec-Fetch-Site; when it's absent we
    fall back to Origin; requests carrying neither (curl, scripts, the
    TestClient) aren't browsers and can't be CSRF'd."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
        site = request.headers.get("sec-fetch-site")
        if site is not None:
            if site not in ("same-origin", "none"):
                return JSONResponse(status_code=403,
                                    content={"detail": "cross-origin request refused"})
        else:
            origin = request.headers.get("origin")
            if origin:
                expected = f"{request.url.scheme}://{request.url.netloc}"
                if origin.rstrip("/") != expected:
                    return JSONResponse(status_code=403,
                                        content={"detail": "cross-origin request refused"})
    return await call_next(request)


from tarot import oidc as oidc_mod  # noqa: E402

app.include_router(oidc_mod.router)


@app.on_event("startup")
def _admin_bootstrap() -> None:
    oidc_mod.ensure_setup_token()


# Release version, threaded in from the git tag at image build time
# (Dockerfile ARG -> ENV). Unset in local/dev builds -> "dev".
VERSION = os.getenv("TAROT_VERSION", "dev")


@app.on_event("startup")
def _dedupe_existing() -> None:
    threading.Thread(target=dedupe.dedupe_all, daemon=True).start()


@app.on_event("startup")
def _reap_sessions() -> None:
    def loop() -> None:
        while True:
            try:
                sessions.reap()
            except Exception:
                pass  # bookkeeping; never a reason to crash
            time.sleep(86400)

    threading.Thread(target=loop, name="session-reaper", daemon=True).start()

IMAGE_CACHE = {"Cache-Control": "public, max-age=604800"}

MEANINGS: dict[str, dict] = json.loads(
    (Path(__file__).parent.parent / "data" / "meanings.json").read_text()
)

# A. E. Waite, The Pictorial Key to the Tarot (1911), public domain.
PKT: dict[str, dict] = json.loads(
    (Path(__file__).parent.parent / "data" / "pkt.json").read_text()
)

def resolve_user(request: Request) -> str:
    """Identity for the request, registering the caller on first sight.

    Resolution order (design §3): valid session cookie → trusted proxy
    header (mode-dependent; in legacy mode the header path includes the
    anonymous `local` fallback) → 401 JSON with a login_url, never a
    redirect. Every route resolves identity through this one dependency;
    auth.py stays free of database imports, so the session lookup and the
    registry upsert both live here.
    """
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        user = sessions.resolve(token, auth.session_days())
        if user:
            users.touch(user)
            return user
    if auth.header_trusted(request):
        user = current_user(request)
        if auth.mode() == auth.LEGACY or user != auth.FALLBACK_USER:
            users.touch(user, display_name(request))
            return user
    raise HTTPException(401, "sign in required")


User = Annotated[str, Depends(resolve_user)]


class SetupRequest(BaseModel):
    token: str


@app.post("/api/setup")
def setup(req: SetupRequest, user: User):
    """Promote the currently signed-in user to admin with the one-time
    setup token printed to the container log (no-admin boots only)."""
    if not oidc_mod.consume_setup_token(req.token.strip(), user):
        raise HTTPException(403, "invalid or already-used setup token")
    return {"user": user, "is_admin": True}


def get_deck_or_404(slug: str, user: str):
    deck = discover_decks(user).get(slug)
    if not deck:
        raise HTTPException(404, f"deck '{slug}' not found")
    return deck


@app.exception_handler(limits.LimitExceeded)
async def _limit_exceeded(request: Request, exc: limits.LimitExceeded):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=429, content={"detail": str(exc)})


def _draw_fingerprint(prefix: str, user: str, question: str | None, cards: list[dict],
                      _normalize: bool = True) -> str:
    """Content hash of a draw, so re-interpreting/recreating the same spread
    charges the daily readings cap exactly once. The question is normalized
    (whitespace collapsed, case folded) so trivial retyping isn't a second
    charge; card order is deliberately ignored (same cards = same reading)."""
    import hashlib

    q = question or ""
    if _normalize:
        q = " ".join(q.split()).casefold()
    payload = json.dumps(
        [user, q, sorted((c["card"]["index"], bool(c.get("reversed"))) for c in cards)]
    )
    return f"{prefix}:{hashlib.sha256(payload.encode()).hexdigest()}"


def _draw_fingerprints(prefix: str, user: str, question: str | None, cards: list[dict]) -> tuple[str, str | None]:
    """(fingerprint, legacy_fingerprint) — legacy is the pre-normalization
    hash, checked on lookup so readings charged before the change never
    re-bill; None when the two coincide."""
    fp = _draw_fingerprint(prefix, user, question, cards)
    legacy = _draw_fingerprint(prefix, user, question, cards, _normalize=False)
    return fp, (legacy if legacy != fp else None)


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION}


@app.get("/api/me")
def me(request: Request, user: User):
    authenticated = is_authenticated(request)
    return {
        "user": user,
        "display_name": _my_display_name(request, user),
        "interpretation": interp.config() is not None,
        "tts": tts.config() is not None,
        "settings": get_my_settings(user),
        "limits": limits.status(user) if limits.enabled() else {"enabled": False},
        "is_admin": is_admin(user),
        "authenticated": authenticated,
        # oidc sessions log out through the app (POST /auth/logout); the
        # legacy/header path keeps the proxy's sign-out URL.
        "logout_url": ("/auth/logout" if request.cookies.get(auth.COOKIE_NAME)
                       else LOGOUT_URL) if authenticated else None,
        "version": VERSION,
    }


@app.get("/api/users")
def users_list(user: User):
    """People who can be picked as share recipients."""
    overrides = db.display_name_overrides()
    return [
        {"username": u["username"],
         "display_name": overrides.get(u["username"]) or u["display_name"]}
        for u in users.list_people()
    ]


@app.get("/api/cards")
def list_cards():
    out = []
    for c in CARDS:
        m = MEANINGS.get(str(c.index), {})
        p = PKT.get(str(c.index), {})
        out.append({
            **asdict(c),
            "upright": m.get("upright"),
            "reversed_meaning": m.get("reversed"),
            "description": p.get("description"),
            "pkt_upright": p.get("upright"),
            "pkt_reversed": p.get("reversed"),
        })
    return out


def _controls_deck(d, user: str) -> bool:
    """Who may curate a deck (incl. its companion-book links): the staging
    owner, the library publisher, or an admin (builtin decks: admin only)."""
    if d.tier == decks_mod.STAGING:
        return d.owner == user
    if d.tier == decks_mod.LIBRARY:
        return d.published_by == user or is_admin(user)
    return is_admin(user)


class DeckPatch(BaseModel):
    tile_cover: bool | None = None


@app.patch("/api/decks/{slug}")
def patch_deck(slug: str, req: DeckPatch, user: User):
    """Owner-curated deck presentation options."""
    deck = get_deck_or_404(slug, user)
    if not _controls_deck(deck, user):
        raise HTTPException(403, "only the deck's owner can change this")
    if req.tile_cover is not None:
        if req.tile_cover and deck.cover is None:
            raise HTTPException(400, "this deck has no cover image")
        decks_mod.update_manifest(deck.path, tile_cover=True if req.tile_cover else None)
    return {"slug": slug, "tile_cover": bool(req.tile_cover)}


class DeckBooksRequest(BaseModel):
    books: list[str]


@app.put("/api/decks/{slug}/books")
def set_deck_books(slug: str, req: DeckBooksRequest, user: User):
    """Curate a deck's companion guidebooks. Deck-side authority only —
    general books never attach themselves to decks."""
    deck = get_deck_or_404(slug, user)
    if not _controls_deck(deck, user):
        raise HTTPException(403, "only the deck's owner can curate its companion books")
    known = books_mod.discover_books(user)
    bad = [b for b in req.books if b not in known]
    if bad:
        raise HTTPException(400, f"unknown book(s): {', '.join(bad)}")
    decks_mod.update_manifest(deck.path, books=req.books or None)
    return {"slug": slug, "books": req.books}


@app.get("/api/decks")
def list_decks(user: User):
    visible_books = books_mod.discover_books(user)
    return [
        {
            "slug": d.slug,
            "name": d.name,
            "source": d.source,
            "attribution": d.attribution,
            "license": d.license,
            "count": len(d.cards),
            "complete": d.complete,
            "majors_only": d.majors_only,
            "extras": [{"index": i, "name": n} for i, n, _ in d.extras],
            "suit_names": d.suit_names,
            "major_names": d.major_names,
            "missing": [] if d.complete else sorted(set(range(78)) - set(d.cards)),
            "has_back": d.back is not None,
            "has_cover": d.cover is not None,
            "owner": d.owner,
            "tier": d.tier,
            "published": d.tier == decks_mod.LIBRARY,
            "published_by": d.published_by,
            "yours": d.tier == decks_mod.STAGING and d.owner == user,
            "can_unpublish": d.tier == decks_mod.LIBRARY
            and (d.published_by == user or is_admin(user)),
            "books": d.books,
            "reversed_indices": sorted(d.reversed_cards.keys()),
            "art_version": d.art_version,
            "tile_cover": d.tile_cover,
            "can_edit_books": _controls_deck(d, user),
            "suggested_books": books_mod.suggest_books(d, visible_books)
            if _controls_deck(d, user) else [],
        }
        for d in discover_decks(user).values()
    ]


@app.get("/api/decks/{slug}/cards/{index}")
def card_image(slug: str, index: int, user: User, reversed: bool = False):
    deck = get_deck_or_404(slug, user)
    path = deck.reversed_image_for(index) if reversed else deck.image_for(index)
    if not path:
        raise HTTPException(404, f"card {index} missing from deck '{slug}'")
    return FileResponse(path, headers=IMAGE_CACHE)


@app.get("/api/decks/{slug}/back")
def back_image(slug: str, user: User):
    deck = get_deck_or_404(slug, user)
    if not deck.back:
        raise HTTPException(404, f"deck '{slug}' has no back image")
    return FileResponse(deck.back, headers=IMAGE_CACHE)


@app.get("/api/decks/{slug}/cover")
def cover_image(slug: str, user: User):
    deck = get_deck_or_404(slug, user)
    if not deck.cover:
        raise HTTPException(404, f"deck '{slug}' has no cover image")
    return FileResponse(deck.cover, headers=IMAGE_CACHE)


@app.get("/api/decks/{slug}/export")
def export_deck(slug: str, user: User):
    """Zip a deck back up (numbered card files + back/cover + manifest)."""
    deck = get_deck_or_404(slug, user)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:  # images don't recompress
        for index, path in sorted(deck.cards.items()):
            z.write(path, f"cards/{index:02d}{path.suffix.lower()}")
        for index, path in sorted(deck.reversed_cards.items()):
            if index < 78:
                z.write(path, f"cards/{index:02d}r{path.suffix.lower()}")
            else:
                z.write(path, f"extras/{path.name}")
        if deck.back:
            z.write(deck.back, f"back{deck.back.suffix.lower()}")
        if deck.cover:
            z.write(deck.cover, f"cover{deck.cover.suffix.lower()}")
        manifest = deck.path / "manifest.yaml"
        if manifest.is_file():
            z.write(manifest, "manifest.yaml")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )


def _deck_view(d, user: str) -> dict:
    return {
        "slug": d.slug,
        "name": d.name,
        "tier": d.tier,
        "published": d.tier == decks_mod.LIBRARY,
        "published_by": d.published_by,
        "yours": d.tier == decks_mod.STAGING and d.owner == user,
        "can_unpublish": d.tier == decks_mod.LIBRARY
        and (d.published_by == user or is_admin(user)),
    }


@app.post("/api/decks/{slug}/publish")
def publish_deck(slug: str, user: User):
    """Move one of your private drafts into the shared library."""
    try:
        deck = decks_mod.publish_deck(user, slug, int(time.time()))
    except DeckConflict:
        raise HTTPException(409, f"the library already has a deck '{slug}' — rename yours first")
    if deck is None:
        raise HTTPException(404, f"you have no draft deck '{slug}' to publish")
    return _deck_view(deck, user)


@app.post("/api/decks/{slug}/unpublish")
def unpublish_deck(slug: str, user: User):
    """Move a library deck back to its publisher's drafts."""
    try:
        deck = decks_mod.unpublish_deck(user, slug, is_admin(user), int(time.time()))
    except DeckForbidden:
        raise HTTPException(403, "only the publisher or an admin can unpublish this deck")
    except DeckConflict:
        raise HTTPException(409, f"a draft deck '{slug}' already exists in the destination")
    if deck is None:
        raise HTTPException(404, f"no library deck '{slug}'")
    return _deck_view(deck, user)


@app.delete("/api/decks/{slug}")
def delete_deck(slug: str, user: User):
    """Delete one of your private draft decks. Published decks must be
    unpublished (back to a draft) first; builtin decks can't be deleted."""
    if not decks_mod.delete_deck(user, slug):
        raise HTTPException(404, f"you have no draft deck '{slug}' to delete")
    dedupe.prune_orphans()  # drop object-store entries this deck was the last user of
    return {"deleted": slug}


DOWNLOAD_JOBS: dict[str, dict] = {}


class DownloadRequest(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    slug: str | None = None
    name: str | None = None


@app.post("/api/decks/download")
def start_deck_download(req: DownloadRequest, user: User):
    from tarot.downloader.adapters import Template, find_adapter
    from tarot.downloader.cli import download_deck

    source = req.source.strip()
    try:
        adapter = find_adapter(source)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    if isinstance(adapter, Template) and not (req.slug or "").strip():
        raise HTTPException(400, "URL templates need a deck slug")

    job_id = secrets.token_hex(8)
    job = {
        "owner": user,
        "source": source,
        "slug": req.slug,
        "name": req.name,
        "completed": 0,
        "failed": [],
        "total": 78,
        "done": False,
        "error": None,
    }
    DOWNLOAD_JOBS[job_id] = job

    def on_start(slug: str, name: str, total: int) -> None:
        job["slug"], job["name"], job["total"] = slug, name, total

    def on_card(index: int, ok: bool) -> None:
        if ok:
            job["completed"] += 1
        else:
            job["failed"].append(index)

    def run() -> None:
        try:
            deck_dir = download_deck(
                source,
                user_decks_dir(user),
                slug=req.slug or None,
                name=req.name or None,
                delay=0.5,
                on_start=on_start,
                on_card=on_card,
            )
            dedupe.dedupe_deck(deck_dir)
        except BaseException as e:  # noqa: BLE001 — includes SystemExit from the CLI paths
            job["error"] = str(e) or e.__class__.__name__
        finally:
            job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return {"job": job_id}


@app.get("/api/decks/download/{job_id}")
def deck_download_status(job_id: str, user: User):
    job = DOWNLOAD_JOBS.get(job_id)
    if not job or job["owner"] != user:
        raise HTTPException(404, "job not found")
    return {k: v for k, v in job.items() if k != "owner"}


MAX_UPLOAD_BYTES = 300 * 1024 * 1024


@app.post("/api/decks/upload")
def upload_deck(user: User, file: UploadFile = File(...), name: str = Form(...), slug: str = Form("")):
    slug = re.sub(r"[^a-z0-9-]", "-", (slug or name).lower()).strip("-")
    if not slug:
        raise HTTPException(400, "deck needs a name")
    dest = user_decks_dir(user) / slug
    if dest.exists():
        raise HTTPException(409, f"you already have a deck '{slug}'")

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "zip too large")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(400, "not a zip file")

    entries: dict[str, str] = {}  # stem -> zip entry name
    extra_entries: list[str] = []  # anything under an extras/ folder: deck-specific bonus cards
    for entry in zf.namelist():
        base = os.path.basename(entry)
        stem, ext = os.path.splitext(base)
        if not stem or base.startswith(".") or ext.lower() not in IMAGE_EXTS:
            continue
        if "extras" in entry.replace("\\", "/").split("/")[:-1]:
            extra_entries.append(entry)
        else:
            entries.setdefault(stem, entry)

    mapping, back_stem, cover_stem, problems, reversed_mapping = importer.map_filenames(list(entries))
    complete = len(mapping) == 78 or (len(mapping) == 22 and all(i < 22 for i in mapping))
    if not mapping and len(entries) in (78, 22):
        # unrecognizable names but the right count: assign in alphabetical order
        mapping = {i: stem for i, stem in enumerate(sorted(entries))}
        problems = []
        complete = True
    if not complete and problems:
        raise HTTPException(400, "couldn't map these files: " + "; ".join(problems[:10]))
    if len(mapping) < 22:
        raise HTTPException(400, f"only recognized {len(mapping)} cards — see docs/decks.md for naming")

    cards_dir = dest / "cards"
    cards_dir.mkdir(parents=True)
    for index, stem in mapping.items():
        entry = entries[stem]
        ext = os.path.splitext(entry)[1].lower()
        (cards_dir / f"{index:02d}{ext}").write_bytes(zf.read(entry))
    for index, stem in reversed_mapping.items():
        entry = entries[stem]
        ext = os.path.splitext(entry)[1].lower()
        (cards_dir / f"{index:02d}r{ext}").write_bytes(zf.read(entry))
    if back_stem:
        entry = entries[back_stem]
        ext = os.path.splitext(entry)[1].lower()
        (dest / f"back{ext}").write_bytes(zf.read(entry))
    if cover_stem:
        entry = entries[cover_stem]
        ext = os.path.splitext(entry)[1].lower()
        (dest / f"cover{ext}").write_bytes(zf.read(entry))
    if extra_entries:
        extras_dir = dest / "extras"
        extras_dir.mkdir()
        for entry in extra_entries:
            (extras_dir / os.path.basename(entry)).write_bytes(zf.read(entry))
    # A manifest.yaml bundled in the zip (e.g. from deck export) round-trips its
    # descriptive keys. Ownership/publication state never imports; `back` and
    # `cover` are re-detected from the renamed back/cover.<ext> files.
    manifest: dict = {}
    manifest_entry = next((e for e in zf.namelist() if os.path.basename(e) == "manifest.yaml"), None)
    if manifest_entry:
        try:
            uploaded_manifest = yaml.safe_load(zf.read(manifest_entry)) or {}
        except yaml.YAMLError:
            uploaded_manifest = {}
        if isinstance(uploaded_manifest, dict):
            manifest = {
                k: uploaded_manifest[k]
                for k in ("source", "attribution", "license", "suits", "majors", "extras", "tile_cover")
                if uploaded_manifest.get(k)
            }
    manifest["name"] = name
    manifest.setdefault("attribution", f"Uploaded by {user}")
    (dest / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    )
    dedupe.dedupe_deck(dest)
    return {
        "slug": slug,
        "count": len(mapping),
        "majors_only": len(mapping) == 22 and all(i < 22 for i in mapping),
        "warnings": problems,
    }


# --- guidebooks ---------------------------------------------------------------

BOOK_JOBS: dict[str, dict] = {}
MAX_BOOK_UPLOAD_BYTES = 100 * 1024 * 1024


def _book_view(b, user: str) -> dict:
    return {
        "slug": b.slug,
        "name": b.name,
        "author": b.author,
        "tier": b.tier,
        "published": b.tier == decks_mod.LIBRARY,
        "published_by": b.published_by,
        "yours": b.tier == decks_mod.STAGING and b.owner == user,
        "can_unpublish": b.tier == decks_mod.LIBRARY
        and (b.published_by == user or is_admin(user)),
        "pages": b.pages,
        "cards_covered": b.cards_covered,
        "chunk_count": b.chunk_count,
        "llm_assisted": b.llm_assisted,
        "card_pages": {str(k): v for k, v in b.card_pages().items()},
    }


def _passages_by_position(user: str, slugs: list[str], cards: list[dict]) -> dict[int, dict[str, str]]:
    """{position: {book name: passage}} for a drawn spread (extras 78+ have
    no canonical passages; unknown/invisible book slugs drop silently)."""
    if not slugs:
        return {}
    indices = [c["card"]["index"] for c in cards if c["card"]["index"] < 78]
    by_index = books_mod.passages_for_reading(user, slugs, indices)
    return {i: by_index[c["card"]["index"]] for i, c in enumerate(cards)
            if c["card"]["index"] in by_index}


def get_book_or_404(slug: str, user: str):
    book = books_mod.discover_books(user).get(slug)
    if not book:
        raise HTTPException(404, f"no book '{slug}'")
    return book


@app.get("/api/books")
def list_books(user: User):
    return [_book_view(b, user)
            for b in sorted(books_mod.discover_books(user).values(), key=lambda b: b.name.lower())]


def _start_book_import(user: str, slug: str, name: str, dest: Path) -> str:
    job_id = secrets.token_hex(8)
    job = {"owner": user, "slug": slug, "name": name, "stage": "queued",
           "page": 0, "pages": 0, "cards_covered": 0, "llm_assisted": False,
           "failed_pages": [], "done": False, "error": None}
    BOOK_JOBS[job_id] = job

    def on_progress(stage: str, done: int, total: int) -> None:
        job["stage"], job["page"], job["pages"] = stage, done, total

    def run() -> None:
        try:
            result = bookimport.import_book(dest / "source.pdf", dest, user, name,
                                            on_progress=on_progress)
            job.update(result)
            job["failed_pages"] = result.get("failed_pages", [])
        except bookimport.BookImportError as e:
            job["error"] = str(e)
        except BaseException as e:  # noqa: BLE001
            job["error"] = str(e) or e.__class__.__name__
        finally:
            job["stage"] = "done"
            job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return job_id


@app.post("/api/books/upload")
def upload_book(user: User, file: UploadFile = File(...), name: str = Form(...), slug: str = Form("")):
    slug = re.sub(r"[^a-z0-9-]", "-", (slug or name).lower()).strip("-")
    if not slug:
        raise HTTPException(400, "book needs a name")
    dest = user_books_dir(user) / slug
    if dest.exists():
        raise HTTPException(409, f"you already have a book '{slug}'")
    data = file.file.read(MAX_BOOK_UPLOAD_BYTES + 1)
    if len(data) > MAX_BOOK_UPLOAD_BYTES:
        raise HTTPException(413, "PDF too large")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "not a PDF file")
    # An image-only book costs one vision pass; gate like other AI spend.
    limits.check_tokens(user)
    dest.mkdir(parents=True)
    (dest / "source.pdf").write_bytes(data)
    return {"job": _start_book_import(user, slug, name, dest), "slug": slug}


@app.get("/api/books/import/{job_id}")
def book_import_status(job_id: str, user: User):
    job = BOOK_JOBS.get(job_id)
    if not job or job["owner"] != user:
        raise HTTPException(404, "job not found")
    return {k: v for k, v in job.items() if k != "owner"}


@app.post("/api/books/{slug}/reextract")
def reextract_book(slug: str, user: User):
    """Re-run extraction on one of your drafts (recovers a failed import,
    applies extractor upgrades). Vision pages already transcribed are cached
    in pages.jsonl and are not re-paid."""
    dest = user_books_dir(user) / slug
    if not (dest / "source.pdf").is_file():
        raise HTTPException(404, f"you have no draft book '{slug}'")
    limits.check_tokens(user)
    manifest = dest / "manifest.yaml"
    name = slug
    if manifest.is_file():
        name = (yaml.safe_load(manifest.read_text()) or {}).get("name", slug)
    return {"job": _start_book_import(user, slug, name, dest), "slug": slug}


class BookPatch(BaseModel):
    name: str | None = None
    author: str | None = None
    license: str | None = None


@app.patch("/api/books/{slug}")
def patch_book(slug: str, req: BookPatch, user: User):
    """Edit a book's descriptive manifest. Staging owner always may; a
    library book's publisher (or an admin) may too — linking a companion
    deck shouldn't force an unpublish round-trip."""
    book = get_book_or_404(slug, user)
    if book.tier == decks_mod.STAGING:
        allowed = book.owner == user
    else:
        allowed = book.published_by == user or is_admin(user)
    if not allowed:
        raise HTTPException(403, "not your book")
    changes: dict = {}
    if req.name is not None:
        changes["name"] = req.name.strip() or book.slug
    if req.author is not None:
        changes["author"] = req.author.strip() or None
    if req.license is not None:
        changes["license"] = req.license.strip() or None
    if changes:
        decks_mod.update_manifest(book.path, **changes)
    return _book_view(books_mod._load_book(book.path, owner=book.owner, tier=book.tier), user)


@app.post("/api/books/{slug}/publish")
def publish_book(slug: str, user: User):
    try:
        book = books_mod.publish_book(user, slug, int(time.time()))
    except BookConflict:
        raise HTTPException(409, f"the library already has a book '{slug}' — rename yours first")
    if book is None:
        raise HTTPException(404, f"you have no draft book '{slug}' to publish")
    return _book_view(book, user)


@app.post("/api/books/{slug}/unpublish")
def unpublish_book(slug: str, user: User):
    try:
        book = books_mod.unpublish_book(user, slug, is_admin(user), int(time.time()))
    except BookForbidden:
        raise HTTPException(403, "only the publisher or an admin can unpublish this book")
    except BookConflict:
        raise HTTPException(409, f"a draft book '{slug}' already exists in the destination")
    if book is None:
        raise HTTPException(404, f"no library book '{slug}'")
    return _book_view(book, user)


@app.delete("/api/books/{slug}")
def delete_book(slug: str, user: User):
    """Delete one of your draft books (including a failed import that never
    finished). Published books must be unpublished first."""
    if not books_mod.delete_book(user, slug):
        raise HTTPException(404, f"you have no draft book '{slug}' to delete")
    return {"deleted": slug}


@app.get("/api/books/passages/{index}")
def book_passages(index: int, user: User, books: str = ""):
    """Card-detail payload: the selected books' passages for one card.
    Unknown/invisible slugs are silently dropped."""
    if not (0 <= index <= 77):
        raise HTTPException(404, "no such card")
    slugs = [s for s in books.split(",") if s]
    visible = books_mod.discover_books(user)
    out = []
    for slug in slugs:
        book = visible.get(slug)
        if not book:
            continue
        passages = books_mod.passages_for(book, index)
        if passages:
            out.append({"slug": slug, "name": book.name,
                        "passages": [{k: p.get(k) for k in
                                      ("heading", "orientation", "pages", "sections", "text")}
                                     for p in passages]})
    return {"books": out}


@app.get("/api/books/{slug}/pages/{n}")
def book_page_image(slug: str, n: int, user: User):
    book = get_book_or_404(slug, user)
    path = book.page_image(n)
    if not path:
        raise HTTPException(404, f"no page {n}")
    return FileResponse(path, headers=IMAGE_CACHE)


@app.get("/api/spreads")
def list_spreads():
    return SPREADS


DEFAULT_REVERSAL_CHANCE = 25  # percent — "some": reversals stay meaningful because they're uncommon


def reversal_chance() -> int:
    stored = cfgfile.get("reading", "reversal_chance")
    if stored is None:
        stored = db.get_setting("reversal_chance")
    try:
        return max(0, min(100, int(stored)))
    except (TypeError, ValueError):
        return DEFAULT_REVERSAL_CHANCE


class DrawRequest(BaseModel):
    deck: str
    spread: str
    reversals: bool = True
    include_extras: bool = False  # opt-in: deck-specific cards beyond the 78
    question: str | None = Field(default=None, max_length=500)


@app.post("/api/draw")
def draw(req: DrawRequest, user: User):
    deck = get_deck_or_404(req.deck, user)
    spread = SPREADS_BY_SLUG.get(req.spread)
    if not spread:
        raise HTTPException(404, f"spread '{req.spread}' not found")

    available = sorted(deck.cards.keys())
    extras_by_index = {i: n for i, n, _ in deck.extras}
    if req.include_extras:
        available += sorted(extras_by_index)
    if len(available) < len(spread["positions"]):
        raise HTTPException(
            400,
            f"deck '{req.deck}' has {len(available)} cards; "
            f"the {spread['name']} spread needs {len(spread['positions'])}",
        )

    def card_payload(i: int) -> dict:
        if i < 78:
            return asdict(CARDS[i])
        return {"index": i, "name": extras_by_index[i], "arcana": "extra", "suit": None, "rank": None, "number": None}

    rng = secrets.SystemRandom()
    chance = reversal_chance() / 100
    indices = rng.sample(available, len(spread["positions"]))
    drawn = [
        {
            "position": pos,
            "card": card_payload(i),
            "reversed": req.reversals and rng.random() < chance,
        }
        for pos, i in zip(spread["positions"], indices)
    ]
    return {"deck": req.deck, "spread": req.spread, "question": req.question, "cards": drawn}


class InterpretRequest(BaseModel):
    question: str | None = None
    spread: str
    cards: list[dict]
    persona: str | None = None  # "alice" | "selene" | "custom" | None = user default
    books: list[str] = []  # guidebook slugs whose passages inform the reading


@app.post("/api/interpret")
async def interpret_reading(req: InterpretRequest, user: User):
    if interp.config() is None:
        raise HTTPException(404, "LLM interpretation is not configured")
    spread = SPREADS_BY_SLUG.get(req.spread)
    spread_name = spread["name"] if spread else req.spread
    try:
        prompt = interp.resolve_prompt(req.persona)
    except KeyError:
        raise HTTPException(404, f"unknown persona '{req.persona}'")
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        fp, fp_legacy = _draw_fingerprints("quick", user, req.question, req.cards)
    except (KeyError, TypeError):
        raise HTTPException(422, "malformed cards payload")
    # Gate both caps up front, but charge the reading only after the LLM call
    # succeeds — a provider failure (or the token 429 below) must not consume
    # a reading slot. Retrying the same draw stays free by fingerprint.
    await run_in_threadpool(limits.check_tokens, user)
    await run_in_threadpool(limits.precheck_reading, user, fp, fp_legacy)
    passages = await run_in_threadpool(
        _passages_by_position, user, req.books, req.cards)
    try:
        text = await interp.interpret(req.question, spread_name, req.cards, system_prompt=prompt,
                                      usage_meta={"owner": user, "kind": "single"},
                                      passages_by_position=passages)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"LLM endpoint error: {e}")
    try:
        await run_in_threadpool(limits.charge_reading, user, fp, fp_legacy)
    except limits.LimitExceeded:
        pass  # raced past the precheck: the reading already happened, accept the overshoot
    return {"interpretation": text, "persona": req.persona or interp.default_persona()}


@app.get("/api/personas")
def list_personas(user: User):
    return {
        "personas": [
            {"slug": slug, "name": p["name"], "description": p["description"]}
            for slug, p in interp.PERSONAS.items()
        ],
        "default": interp.default_persona(),
    }


class LlmSettingsRequest(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None  # write-only; empty string clears the stored key


def require_admin(user: str) -> None:
    if not is_admin(user):
        raise HTTPException(403, "admin only")


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    active: bool | None = None
    is_admin: bool | None = None


@app.get("/api/admin/users")
def admin_users_list(user: User):
    require_admin(user)
    return users.list_all()


class ReassignRequest(BaseModel):
    to: str


@app.post("/api/admin/users/{username}/reassign")
def admin_reassign(username: str, req: ReassignRequest, user: User):
    """Hand every owner surface of `username` to another person and
    deactivate the source — the `local` retirement tool (auth Step 7),
    generalized to any user."""
    from tarot import reassign as reassign_mod

    require_admin(user)
    dst = req.to.strip()
    src_row = users.get(username)
    dst_row = users.get(dst)
    if not src_row:
        raise HTTPException(404, f"user '{username}' not found")
    if not dst_row or not dst_row["active"]:
        raise HTTPException(400, f"'{dst}' is not an active user")
    if username == dst:
        raise HTTPException(400, "source and destination are the same user")
    if dst_row["kind"] != users.KIND_PERSON:
        raise HTTPException(400, "destination must be a person")
    if src_row["is_admin"] and src_row["active"] and not users.other_active_admin_exists(username):
        raise HTTPException(409, "cannot deactivate the last active admin")
    # sync route: FastAPI already runs this in the threadpool
    return reassign_mod.reassign_user_data(username, dst)


@app.delete("/api/admin/users/{username}")
def admin_user_delete(username: str, user: User):
    """Erase a user and their data (library publications tombstone to
    "former member"; the usage ledger stays). Admins must be demoted
    first — the two-step makes deleting a privileged account deliberate;
    ordinary users delete directly (the UI confirms)."""
    from tarot import reassign as reassign_mod

    require_admin(user)
    target = users.get(username)
    if not target:
        raise HTTPException(404, f"user '{username}' not found")
    if username == user:
        raise HTTPException(400, "you cannot delete yourself")
    if target["is_admin"]:
        raise HTTPException(409, "remove admin from this user first — admins cannot be deleted")
    return reassign_mod.delete_user(username)


@app.patch("/api/admin/users/{username}")
def admin_user_update(username: str, req: UpdateUserRequest, user: User):
    require_admin(user)
    target = users.get(username)
    if not target:
        raise HTTPException(404, f"user '{username}' not found")
    # Never orphan the instance: the last active admin can be neither
    # deactivated nor demoted.
    if (req.active is False or req.is_admin is False) and target["is_admin"] and target["active"]:
        if not users.other_active_admin_exists(username):
            raise HTTPException(409, "cannot remove the last active admin")
    updated = users.update(username, display_name=req.display_name, active=req.active)
    if req.is_admin is not None:
        updated = users.set_admin(username, req.is_admin) or updated
    if req.active is False:
        sessions.destroy_all(username)  # a deactivated account signs out everywhere
    return updated


@app.get("/api/account")
def account(request: Request, user: User):
    """Everything the current user owns and has shared, for the account page."""
    published = [
        {"slug": d.slug, "name": d.name}
        for d in discover_decks(user).values()
        if d.tier == decks_mod.LIBRARY and d.published_by == user
    ]
    return {
        "user": user,
        "display_name": _my_display_name(request, user),
        "authenticated": is_authenticated(request),
        "is_admin": is_admin(user),
        "reading_count": db.owned_reading_count(user),
        "shares_granted": db.shares_granted(user),
        "shares_received": db.shares_received(user),
        "published_decks": published,
    }


def _managed(section: str, *keys: str) -> list[str]:
    """Settings the config file owns, so the UI can render them read-only."""
    return [k for k in keys if cfgfile.has(section, k)]


@app.get("/api/settings/llm")
def get_llm_settings(user: User):
    require_admin(user)
    managed = _managed("llm", "base_url", "model", "max_tokens")
    if cfgfile.llm_api_key() is not None:
        managed.append("api_key")
    return {
        "base_url": cfgfile.get("llm", "base_url")
        or db.get_setting("llm_base_url")
        or os.environ.get("TAROT_LLM_BASE_URL", ""),
        "model": cfgfile.get("llm", "model")
        or db.get_setting("llm_model")
        or os.environ.get("TAROT_LLM_MODEL", ""),
        "api_key_set": bool(
            cfgfile.llm_api_key()
            or db.get_setting("llm_api_key")
            or os.environ.get("TAROT_LLM_API_KEY")
        ),
        "from_env": not cfgfile.has("llm", "base_url")
        and not db.get_setting("llm_base_url")
        and bool(os.environ.get("TAROT_LLM_BASE_URL")),
        "managed": managed,
        "config_file": str(cfgfile.config_path()) if cfgfile.exists() else None,
        "config_error": cfgfile.error() or None,
    }


def _reject_managed(section: str, **fields) -> None:
    """The config file is authoritative; saving over it would look like it
    worked and then be ignored, so refuse instead."""
    clashes = [
        k
        for k, v in fields.items()
        if v is not None
        and (cfgfile.llm_api_key() is not None if k == "api_key" else cfgfile.has(section, k))
    ]
    if clashes:
        raise HTTPException(
            409,
            f"{', '.join(sorted(clashes))} managed by {cfgfile.config_path()} — edit the config file",
        )


@app.put("/api/settings/llm")
def set_llm_settings(req: LlmSettingsRequest, user: User):
    require_admin(user)
    _reject_managed("llm", base_url=req.base_url, model=req.model, api_key=req.api_key)
    if req.base_url is not None:
        db.set_setting("llm_base_url", req.base_url.strip())
    if req.model is not None:
        db.set_setting("llm_model", req.model.strip())
    if req.api_key is not None:
        db.set_setting("llm_api_key", crypto.encrypt(req.api_key.strip()) if req.api_key.strip() else "")
    return get_llm_settings(user)


class ReadingSettingsRequest(BaseModel):
    reversal_chance: int = Field(ge=0, le=100)


@app.get("/api/settings/reading")
def get_reading_settings(user: User):
    require_admin(user)
    return {
        "reversal_chance": reversal_chance(),
        "default": DEFAULT_REVERSAL_CHANCE,
        "managed": _managed("reading", "reversal_chance"),
        "config_file": str(cfgfile.config_path()) if cfgfile.exists() else None,
    }


@app.put("/api/settings/reading")
def set_reading_settings(req: ReadingSettingsRequest, user: User):
    require_admin(user)
    _reject_managed("reading", reversal_chance=req.reversal_chance)
    db.set_setting(
        "reversal_chance",
        "" if req.reversal_chance == DEFAULT_REVERSAL_CHANCE else str(req.reversal_chance),
    )
    return get_reading_settings(user)


class LimitsSettingsRequest(BaseModel):
    # None = leave alone; 0 = disable (stored as unset)
    readings_per_day: float | None = Field(default=None, ge=0)
    llm_tokens_per_day: float | None = Field(default=None, ge=0)
    tts_minutes_per_day: float | None = Field(default=None, ge=0)


@app.get("/api/settings/limits")
def get_limits_settings(user: User):
    require_admin(user)
    return {
        **limits.config(),
        "managed": _managed("limits", *limits.KEYS),
        "config_file": str(cfgfile.config_path()) if cfgfile.exists() else None,
        "config_error": cfgfile.error() or None,
    }


@app.put("/api/settings/limits")
def set_limits_settings(req: LimitsSettingsRequest, user: User):
    require_admin(user)
    _reject_managed("limits", **req.model_dump())
    for key in limits.KEYS:
        value = getattr(req, key)
        if value is not None:
            db.set_setting(f"limit_{key}", "" if value == 0 else str(value))
    return get_limits_settings(user)


# The migrated device-preference keys (formerly localStorage): stored as
# opaque strings — the frontend owns their meaning; the server only bounds
# their size. `extras` fans out to one `extras.<slug>` row per deck.
PREF_STR_KEYS = ("deck", "spread", "reversals", "persona", "guided_mode", "journal_layout")
PREF_LIST_KEYS = ("fav_decks", "recent_decks")


class UserSettingsRequest(BaseModel):
    auto_read_audio: bool | None = None
    hide_draft_decks: bool | None = None
    default_books: list[str] | None = None
    deck: str | None = Field(default=None, max_length=200)
    spread: str | None = Field(default=None, max_length=200)
    reversals: str | None = Field(default=None, max_length=20)
    persona: str | None = Field(default=None, max_length=100)
    guided_mode: str | None = Field(default=None, max_length=20)
    journal_layout: str | None = Field(default=None, max_length=20)
    fav_decks: list[str] | None = None
    recent_decks: list[str] | None = None
    extras: dict[str, bool] | None = None  # {deck_slug: include_extras}


def _default_books(user: str) -> list[str]:
    try:
        v = json.loads(db.get_user_setting(user, "default_books") or "[]")
        return [s for s in v if isinstance(s, str)] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _json_list(raw: str) -> list[str]:
    try:
        v = json.loads(raw or "[]")
        return [s for s in v if isinstance(s, str)] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


@app.get("/api/settings/me")
def get_my_settings(user: User):
    """The full per-user profile — every preference follows the account
    across devices. `has_profile` tells the frontend whether the migrated
    device prefs have ever been written (drives the one-time first-login
    import from localStorage)."""
    stored = db.user_settings_all(user)
    profile_keys = set(PREF_STR_KEYS) | set(PREF_LIST_KEYS)
    return {
        "auto_read_audio": stored.get("auto_read_audio") == "true",
        "hide_draft_decks": stored.get("hide_draft_decks") == "true",
        "default_books": _default_books(user),
        **{k: (stored[k] if k in stored else None) for k in PREF_STR_KEYS},
        **{k: (_json_list(stored[k]) if k in stored else None) for k in PREF_LIST_KEYS},
        "extras": {k[len("extras."):]: v == "true"
                   for k, v in stored.items() if k.startswith("extras.")},
        "has_profile": any(k in stored for k in profile_keys)
                       or any(k.startswith("extras.") for k in stored),
    }


@app.put("/api/settings/me")
def set_my_settings(req: UserSettingsRequest, user: User):
    if req.auto_read_audio is not None:
        db.set_user_setting(user, "auto_read_audio", "true" if req.auto_read_audio else "false")
    if req.hide_draft_decks is not None:
        db.set_user_setting(user, "hide_draft_decks", "true" if req.hide_draft_decks else "false")
    if req.default_books is not None:
        known = books_mod.discover_books(user)
        db.set_user_setting(user, "default_books",
                            json.dumps([s for s in req.default_books if s in known]))
    for key in PREF_STR_KEYS:
        value = getattr(req, key)
        if value is not None:
            db.set_user_setting(user, key, value)
    for key in PREF_LIST_KEYS:
        value = getattr(req, key)
        if value is not None:
            db.set_user_setting(user, key, json.dumps([s for s in value if isinstance(s, str)][:50]))
    if req.extras is not None:
        for slug, include in list(req.extras.items())[:50]:
            db.set_user_setting(user, f"extras.{slug[:100]}", "true" if include else "false")
    return get_my_settings(user)


class MeRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)


@app.patch("/api/me")
def patch_me(req: MeRequest, request: Request, user: User):
    """Self-service profile edits. A blank display_name clears the override,
    falling back to the identity-derived name (users.touch keeps rewriting
    the registry row from the header, so the override lives in
    user_settings where nothing clobbers it)."""
    if req.display_name is not None:
        db.set_user_setting(user, "display_name", req.display_name.strip())
    return {"display_name": _my_display_name(request, user)}


def _my_display_name(request: Request, user: str) -> str:
    """Self-chosen override → header-derived name → the registry row (the
    only source for cookie-session requests, which carry no header)."""
    override = db.get_user_setting(user, "display_name")
    if override:
        return override
    if auth._raw_identity(request):
        return display_name(request)
    row = users.get(user)
    return row["display_name"] if row else display_name(request)


@app.get("/api/admin/usage")
def admin_usage(user: User, days: int = 30):
    """Token/character/audio spend of the connected AI components, for the
    admin usage view. Ledger rows are written per provider call; cache hits
    and aborted streams cost nothing and record nothing."""
    require_admin(user)
    return db.usage_summary(max(1, min(days, 365)))


class VoiceBlock(BaseModel):
    voice: str | None = None
    speed: float | None = Field(default=None, ge=0.25, le=4.0)
    instructions: str | None = Field(default=None, max_length=2000)


class SaveReadingRequest(BaseModel):
    deck: str
    spread: str
    question: str | None = None
    cards: list[dict]
    notes: str = ""
    books: list[str] = []  # guidebooks that informed the quick interpretation


class UpdateReadingRequest(BaseModel):
    notes: str | None = None


class SharingRequest(BaseModel):
    visibility: str
    grantees: list[str] = Field(default_factory=list)


def _reading_view(r: dict, user: str) -> dict:
    """Only the owner sees who a reading is shared with."""
    yours = r["owner"] == user
    return {**r, "yours": yours, "shared_with": r["shared_with"] if yours else []}


@app.get("/api/readings")
def readings_list(user: User):
    return [_reading_view(r, user) for r in db.list_readings(user)]


@app.post("/api/readings")
def readings_save(req: SaveReadingRequest, user: User):
    r = db.save_reading(user, req.question, req.deck, req.spread, req.cards, notes=req.notes)
    if req.books:
        db.set_reading_books(r["id"], user, req.books)
        r["books"] = sorted(set(req.books))
    return r


@app.get("/api/readings/{reading_id}")
def readings_get(reading_id: int, user: User):
    r = db.get_reading(reading_id, user)
    if not r:
        raise HTTPException(404, "reading not found")
    return _reading_view(r, user)


@app.patch("/api/readings/{reading_id}")
def readings_update(reading_id: int, req: UpdateReadingRequest, user: User):
    r = db.update_reading(reading_id, user, notes=req.notes)
    if not r:
        raise HTTPException(404, "reading not found or not yours")
    return _reading_view(r, user)


@app.put("/api/readings/{reading_id}/sharing")
def readings_set_sharing(reading_id: int, req: SharingRequest, user: User):
    if req.visibility not in db.VISIBILITIES:
        raise HTTPException(400, f"visibility must be one of {', '.join(db.VISIBILITIES)}")

    grantees: list[str] = []
    if req.visibility == db.SPECIFIC:
        for g in dict.fromkeys(req.grantees):  # de-dupe, keep order
            if g == user:
                continue  # sharing with yourself is a no-op, not an error
            if not users.is_grantable(g):
                raise HTTPException(400, f"cannot share with '{g}'")
            grantees.append(g)

    r = db.set_sharing(reading_id, user, req.visibility, grantees)
    if not r:
        raise HTTPException(404, "reading not found or not yours")
    return _reading_view(r, user)


@app.delete("/api/readings/{reading_id}")
def readings_delete(reading_id: int, user: User):
    if not db.delete_reading(reading_id, user):
        raise HTTPException(404, "reading not found or not yours")
    return {"deleted": reading_id}


# --- Guided reading (card-by-card streamed interpretation) ---------------------

GUIDED_MODES = ("isolated", "cumulative")


class GuidedReadingRequest(BaseModel):
    deck: str
    spread: str
    question: str | None = None
    cards: list[dict]
    mode: str = "isolated"
    notes: str = ""


class StreamInterpretRequest(BaseModel):
    persona: str | None = None  # fixed for the reading; sent on each streamed call
    books: list[str] = []  # guidebook slugs whose passages inform this call


@app.post("/api/readings/guided")
def create_guided(req: GuidedReadingRequest, user: User):
    """Create the in-progress guided reading up front (resumable)."""
    if req.mode not in GUIDED_MODES:
        raise HTTPException(400, f"mode must be one of {', '.join(GUIDED_MODES)}")
    # Content-hash fingerprint so the charge lands before the row exists and a
    # duplicate create of the same draw never double-bills. Both caps gate only
    # the START of a reading — once created, it can always be finished.
    limits.check_tokens(user)
    limits.charge_reading(user, *_draw_fingerprints("guided", user, req.question, req.cards))
    r = db.create_guided_reading(
        user, req.question, req.deck, req.spread, req.cards, req.mode, notes=req.notes
    )
    return _reading_view(r, user)


def _resolve_persona_or_400(persona: str | None, user: str) -> str:
    if interp.config() is None:
        raise HTTPException(404, "LLM interpretation is not configured")
    try:
        return interp.resolve_prompt(persona)
    except KeyError:
        raise HTTPException(404, f"unknown persona '{persona}'")
    except ValueError as e:
        raise HTTPException(400, str(e))


def _stream_and_persist(request: Request, user: str, persona: str | None,
                        system_prompt: str, user_content: str, persist,
                        max_tokens: int | None = None,
                        usage_meta: dict | None = None):
    """Shared SSE generator: stream deltas, then persist the full text at natural
    completion only (skipped on disconnect / mid-stream error), then `done`."""
    async def gen():
        parts: list[str] = []
        agen = interp.interpret_stream(system_prompt, user_content, max_tokens=max_tokens,
                                       usage_meta=usage_meta)
        try:
            async for delta in agen:
                if await request.is_disconnected():
                    # Client left — close the upstream stream now (don't wait for
                    # GC) so we stop paying the LLM; persist nothing.
                    await agen.aclose()
                    return
                parts.append(delta)
                yield sse.sse("token", {"text": delta})
        except httpx.HTTPError as e:
            yield sse.sse("error", {"message": f"LLM endpoint error: {e}"})
            return
        except Exception:
            yield sse.sse("error", {"message": "interpretation failed"})
            return
        full = "".join(parts).strip()
        if not full:
            # An empty completion is a failure, not a result: persisting
            # nothing while signalling `done` would strand the reading
            # in_progress with the client believing it finished.
            yield sse.sse("error", {"message": "the model returned an empty response — try again"})
            return
        await run_in_threadpool(persist, full)
        yield sse.sse("done", {"persona": persona or interp.default_persona()})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=sse.SSE_HEADERS)


@app.post("/api/readings/{reading_id}/interpret/focused/{position}")
def interpret_focused(reading_id: int, position: int, req: StreamInterpretRequest,
                      request: Request, user: User):
    reading = db.get_reading(reading_id, user)
    if not reading or reading["owner"] != user:
        raise HTTPException(404, "reading not found or not yours")
    cards = reading["cards"]
    if position < 0 or position >= len(cards):
        raise HTTPException(404, f"no card at position {position}")
    prompt = _resolve_persona_or_400(req.persona, user)
    # Caps gate the START of a reading: one charged at creation streams free
    # forever (even across midnight), but a never-charged reading (saved via
    # plain POST /api/readings) pays its one charge the first time
    # interpretation begins — otherwise the readings cap has a free side door.
    # No token check: a reading you were allowed to start can always be
    # finished (overshoot is bounded by one reading).
    limits.charge_reading_once(
        user, *_draw_fingerprints("guided", user, reading["question"], reading["cards"]))

    spread = SPREADS_BY_SLUG.get(reading["spread"])
    spread_name = spread["name"] if spread else reading["spread"]
    passages = _passages_by_position(user, req.books, [cards[position]]).get(0)
    if reading["interpretation"]["mode"] == "cumulative":
        focused = db.get_focused_interpretations(reading_id, user)
        prior = [(cards[i], focused.get(i)) for i in range(position) if i < len(cards)]
        content = interp.describe_card(reading["question"], spread_name, cards[position],
                                       prior=prior, passages=passages)
    else:
        content = interp.describe_card(reading["question"], spread_name, cards[position],
                                       passages=passages)

    def persist(text: str):
        db.set_focused_interpretation(reading_id, user, position, text, persona=req.persona)
        if req.books:
            db.set_reading_books(reading_id, user, req.books)

    return _stream_and_persist(request, user, req.persona, prompt, content, persist,
                               usage_meta={"owner": user, "kind": "focused", "reading_id": reading_id})


@app.post("/api/readings/{reading_id}/interpret/comprehensive")
def interpret_comprehensive(reading_id: int, req: StreamInterpretRequest,
                            request: Request, user: User):
    reading = db.get_reading(reading_id, user)
    if not reading or reading["owner"] != user:
        raise HTTPException(404, "reading not found or not yours")
    prompt = _resolve_persona_or_400(req.persona, user)
    # Same charge-on-start rule as interpret_focused; finishing an already-
    # charged reading is never blocked.
    limits.charge_reading_once(
        user, *_draw_fingerprints("guided", user, reading["question"], reading["cards"]))

    spread = SPREADS_BY_SLUG.get(reading["spread"])
    spread_name = spread["name"] if spread else reading["spread"]
    focused = db.get_focused_interpretations(reading_id, user)
    content = interp.describe_comprehensive(
        reading["question"], spread_name, reading["cards"], focused,
        passages_by_position=_passages_by_position(user, req.books, reading["cards"]))

    def persist(text: str):
        db.set_comprehensive_interpretation(reading_id, user, text, persona=req.persona)
        if req.books:
            db.set_reading_books(reading_id, user, req.books)

    # The comprehensive synthesis grows with the spread — a 10-card Celtic Cross
    # walkthrough truncated at the default cap. Give it room scaled to card count
    # (never below the configured cap).
    n = len(reading["cards"])
    cfg = interp.config()
    base = (cfg or {}).get("max_tokens") or interp.DEFAULT_MAX_TOKENS
    max_tokens = max(base, 400 + 220 * n)
    return _stream_and_persist(request, user, req.persona, prompt, content, persist,
                               max_tokens=max_tokens,
                               usage_meta={"owner": user, "kind": "comprehensive",
                                           "reading_id": reading_id})


# no-cache (NOT no-store): the URL stays stable while the audio behind it
# changes whenever the persona's voice settings do, so the browser must
# revalidate on every play. The ETag is the TTS cache key (script+voice+
# model+base_url), and we answer If-None-Match ourselves — Starlette's
# FileResponse sets an ETag but never returns 304, so without this every
# replay re-downloaded the full file.
AUDIO_CACHE = {"Cache-Control": "private, no-cache"}


def _audio_response(request: Request, path, key: str):
    etag = f'"{key}"'
    headers = {**AUDIO_CACHE, "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type="audio/mpeg", headers=headers)


def _tts_config_or_409() -> dict:
    cfg = tts.config()
    if cfg is None:
        raise HTTPException(409, "TTS is not configured")
    return cfg


@app.get("/api/readings/{reading_id}/audio/{position}")
async def reading_audio(reading_id: int, position: int, request: Request, user: User,
                        persona: str | None = None):
    """Spoken audio for one interpretation piece (position -1 = the whole-spread
    row). Anyone who can see the reading can listen; generated on first play,
    cached after. `persona` overrides the voice (the guided page passes its
    reader picker so audio follows the current selection); the text itself
    always stays as written."""
    cfg = _tts_config_or_409()
    reading = await run_in_threadpool(db.get_reading, reading_id, user)
    if not reading:
        raise HTTPException(404, "reading not found")
    row = await run_in_threadpool(db.get_interpretation, reading_id, position)
    if not row:
        raise HTTPException(404, f"no interpretation at position {position}")

    card = reading["cards"][position] if position >= 0 and position < len(reading["cards"]) else None
    script = tts.build_script(tts.spoken_intro(card), row["text"])
    # explicit persona = the requester's choice; stored persona = whoever wrote it
    if persona:
        voice = await run_in_threadpool(tts.resolve_voice, persona, user)
    else:
        voice = await run_in_threadpool(tts.resolve_voice, row["persona"], reading["owner"])
    key = tts.cache_key(script, voice, cfg)
    cached = (tts.cache_dir() / f"{key}.mp3").is_file()
    # An unchanged piece the browser already holds is a 304 before any
    # generation or limit check; the touch keeps the LRU order honest.
    if cached and request.headers.get("if-none-match") == f'"{key}"':
        await run_in_threadpool(db.tts_cache_touch, key)
        return Response(status_code=304, headers={**AUDIO_CACHE, "ETag": f'"{key}"'})
    # cached replays are free and never limit-checked
    if not cached:
        await run_in_threadpool(limits.check_minutes, user)
    try:
        path = await tts.get_or_generate(
            script, voice, cfg,
            usage_meta={"owner": user, "kind": "speak", "reading_id": reading_id})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"TTS endpoint error: {e}")
    return _audio_response(request, path, key)


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    persona: str | None = None  # "alice" | "selene" | "custom" | None = user default


@app.post("/api/tts")
async def tts_speak(req: TtsRequest, user: User):
    """Audio for ephemeral text — the quick reading's one-shot interpretation,
    which is never persisted. Cached like everything else, so replaying the
    same text is free."""
    cfg = _tts_config_or_409()
    persona = req.persona or interp.default_persona()
    voice = await run_in_threadpool(tts.resolve_voice, persona, user)
    script = tts.build_script("Your reading.", req.text)
    key = tts.cache_key(script, voice, cfg)
    if not (tts.cache_dir() / f"{key}.mp3").is_file():
        await run_in_threadpool(limits.check_minutes, user)
    try:
        path = await tts.get_or_generate(script, voice, cfg,
                                         usage_meta={"owner": user, "kind": "speak"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"TTS endpoint error: {e}")
    return FileResponse(path, media_type="audio/mpeg",
                        headers={**AUDIO_CACHE, "ETag": f'"{key}"'})


class TtsSettingsRequest(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None  # write-only; empty string clears the stored key
    voices: dict[str, VoiceBlock] | None = None  # keys: alice / selene


def _file_owns_voices() -> list[str]:
    file_voices = cfgfile.get("tts", "voices")
    if not isinstance(file_voices, dict):
        return []
    return [p for p in tts.VOICE_DEFAULTS if isinstance(file_voices.get(p), dict)]


@app.get("/api/settings/tts")
def get_tts_settings(user: User):
    require_admin(user)
    managed = _managed("tts", "base_url", "model")
    if cfgfile.tts_api_key() is not None:
        managed.append("api_key")
    managed += [f"voice_{p}" for p in _file_owns_voices()]
    return {
        "base_url": cfgfile.get("tts", "base_url")
        or db.get_setting("tts_base_url")
        or os.environ.get("TAROT_TTS_BASE_URL", ""),
        "model": cfgfile.get("tts", "model")
        or db.get_setting("tts_model")
        or os.environ.get("TAROT_TTS_MODEL", "")
        or tts.DEFAULT_MODEL,
        "api_key_set": bool(
            cfgfile.tts_api_key()
            or db.get_setting("tts_api_key")
            or os.environ.get("TAROT_TTS_API_KEY")
        ),
        "voices": {p: tts.resolve_voice(p, user) for p in tts.VOICE_DEFAULTS},
        "defaults": tts.VOICE_DEFAULTS,
        "managed": managed,
        "config_file": str(cfgfile.config_path()) if cfgfile.exists() else None,
        "config_error": cfgfile.error() or None,
    }


@app.put("/api/settings/tts")
def set_tts_settings(req: TtsSettingsRequest, user: User):
    require_admin(user)
    _reject_managed("tts", base_url=req.base_url, model=req.model)
    if req.api_key is not None and cfgfile.tts_api_key() is not None:
        raise HTTPException(
            409, f"api_key managed by {cfgfile.config_path()} — edit the config file"
        )
    if req.voices:
        file_owned = set(_file_owns_voices())
        clashes = sorted(set(req.voices) & file_owned)
        if clashes:
            raise HTTPException(
                409,
                f"voices ({', '.join(clashes)}) managed by {cfgfile.config_path()} — edit the config file",
            )
    if req.base_url is not None:
        db.set_setting("tts_base_url", req.base_url.strip())
    if req.model is not None:
        db.set_setting("tts_model", req.model.strip())
    if req.api_key is not None:
        db.set_setting("tts_api_key", crypto.encrypt(req.api_key.strip()) if req.api_key.strip() else "")
    for persona, block in (req.voices or {}).items():
        if persona not in tts.VOICE_DEFAULTS:
            raise HTTPException(400, f"unknown persona '{persona}'")
        values = {k: v for k, v in block.model_dump().items() if v is not None}
        db.set_setting(f"tts_voice_{persona}", json.dumps(values) if values else "")
    return get_tts_settings(user)


class SpaStaticFiles(StaticFiles):
    """Static files with SPA fallback: unknown paths serve index.html."""

    async def get_response(self, path, scope):
        try:
            resp = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            path, resp = "index.html", await super().get_response("index.html", scope)

        # A bare "/" arrives as "." (normpath), which html=True resolves to
        # index.html.
        name = path.rsplit("/", 1)[-1]
        if name in ("", "."):
            name = "index.html"
        if name in ("service-worker.js", "index.html"):
            # MUST NOT be cached by any intermediary. A stale service worker is
            # unrecoverable from the client: the browser's update check is
            # answered from the edge cache, so it never learns a new one exists
            # and keeps serving an app shell whose hashed assets are long gone.
            # (Cloudflare edge-cached this one for 3 days and blanked the app
            # for external users after v0.8.0 — 2026-07-24.)
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
        elif "/immutable/" in path:
            # Content-hashed by the build; safe to cache hard.
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


# Serve the built frontend (present in the container; absent in API-only dev).
_static = Path(os.environ.get("TAROT_STATIC_DIR", Path(__file__).parent.parent.parent.parent / "frontend" / "build"))
if _static.is_dir():
    app.mount("/", SpaStaticFiles(directory=_static, html=True), name="frontend")
