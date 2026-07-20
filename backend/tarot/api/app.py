import io
import json
import os
import re
import secrets
import threading
import zipfile

import httpx
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from tarot import crypto, db, dedupe, importer, interpret as interp
from tarot.auth import current_user, is_admin
from tarot.cards import CARDS
from tarot.decks import IMAGE_EXTS, discover_decks, set_deck_shared, user_decks_dir
from tarot.spreads import SPREADS, SPREADS_BY_SLUG

app = FastAPI(title="Tarotarium", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.on_event("startup")
def _dedupe_existing() -> None:
    threading.Thread(target=dedupe.dedupe_all, daemon=True).start()

IMAGE_CACHE = {"Cache-Control": "public, max-age=604800"}

MEANINGS: dict[str, dict] = json.loads(
    (Path(__file__).parent.parent / "data" / "meanings.json").read_text()
)

# A. E. Waite, The Pictorial Key to the Tarot (1911), public domain.
PKT: dict[str, dict] = json.loads(
    (Path(__file__).parent.parent / "data" / "pkt.json").read_text()
)

User = Annotated[str, Depends(current_user)]


def get_deck_or_404(slug: str, user: str):
    deck = discover_decks(user).get(slug)
    if not deck:
        raise HTTPException(404, f"deck '{slug}' not found")
    return deck


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/me")
def me(user: User):
    return {
        "user": user,
        "interpretation": interp.config() is not None,
        "is_admin": is_admin(user),
    }


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


@app.get("/api/decks")
def list_decks(user: User):
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
            "missing": [] if d.complete else sorted(set(range(78)) - set(d.cards)),
            "has_back": d.back is not None,
            "owner": d.owner,
            "shared": d.shared,
            "yours": d.owner == user,
        }
        for d in discover_decks(user).values()
    ]


@app.get("/api/decks/{slug}/cards/{index}")
def card_image(slug: str, index: int, user: User):
    deck = get_deck_or_404(slug, user)
    path = deck.image_for(index)
    if not path:
        raise HTTPException(404, f"card {index} missing from deck '{slug}'")
    return FileResponse(path, headers=IMAGE_CACHE)


@app.get("/api/decks/{slug}/back")
def back_image(slug: str, user: User):
    deck = get_deck_or_404(slug, user)
    if not deck.back:
        raise HTTPException(404, f"deck '{slug}' has no back image")
    return FileResponse(deck.back, headers=IMAGE_CACHE)


class ShareRequest(BaseModel):
    shared: bool


@app.get("/api/decks/{slug}/export")
def export_deck(slug: str, user: User):
    """Zip a deck back up (numbered card files + back + manifest) for download."""
    deck = get_deck_or_404(slug, user)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:  # images don't recompress
        for index, path in sorted(deck.cards.items()):
            z.write(path, f"cards/{index:02d}{path.suffix.lower()}")
        if deck.back:
            z.write(deck.back, f"back{deck.back.suffix.lower()}")
        manifest = deck.path / "manifest.yaml"
        if manifest.is_file():
            z.write(manifest, "manifest.yaml")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )


@app.post("/api/decks/{slug}/share")
def share_deck(slug: str, req: ShareRequest, user: User):
    deck = get_deck_or_404(slug, user)
    if deck.owner != user:
        raise HTTPException(403, "only the deck's owner can change sharing")
    set_deck_shared(deck, req.shared)
    return {"slug": slug, "shared": req.shared}


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

    mapping, back_stem, problems = importer.map_filenames(list(entries))
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
    if back_stem:
        entry = entries[back_stem]
        ext = os.path.splitext(entry)[1].lower()
        (dest / f"back{ext}").write_bytes(zf.read(entry))
    if extra_entries:
        extras_dir = dest / "extras"
        extras_dir.mkdir()
        for entry in extra_entries:
            (extras_dir / os.path.basename(entry)).write_bytes(zf.read(entry))
    (dest / "manifest.yaml").write_text(
        yaml.safe_dump({"name": name, "attribution": f"Uploaded by {user}"}, sort_keys=False, allow_unicode=True)
    )
    dedupe.dedupe_deck(dest)
    return {
        "slug": slug,
        "count": len(mapping),
        "majors_only": len(mapping) == 22 and all(i < 22 for i in mapping),
        "warnings": problems,
    }


@app.get("/api/spreads")
def list_spreads():
    return SPREADS


DEFAULT_REVERSAL_CHANCE = 25  # percent — "some": reversals stay meaningful because they're uncommon


def reversal_chance() -> int:
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


@app.post("/api/interpret")
async def interpret_reading(req: InterpretRequest, user: User):
    if interp.config() is None:
        raise HTTPException(404, "LLM interpretation is not configured")
    spread = SPREADS_BY_SLUG.get(req.spread)
    spread_name = spread["name"] if spread else req.spread
    try:
        prompt = interp.resolve_prompt(req.persona, db.get_user_prompt(user))
    except KeyError:
        raise HTTPException(404, f"unknown persona '{req.persona}'")
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        text = await interp.interpret(req.question, spread_name, req.cards, system_prompt=prompt)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"LLM endpoint error: {e}")
    return {"interpretation": text, "persona": req.persona or ("custom" if db.get_user_prompt(user) else interp.DEFAULT_PERSONA)}


@app.get("/api/personas")
def list_personas(user: User):
    return {
        "personas": [
            {"slug": slug, "name": p["name"], "description": p["description"]}
            for slug, p in interp.PERSONAS.items()
        ],
        "has_custom": bool(db.get_user_prompt(user)),
        "default": interp.DEFAULT_PERSONA,
    }


class LlmSettingsRequest(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None  # write-only; empty string clears the stored key


def require_admin(user: str) -> None:
    if not is_admin(user):
        raise HTTPException(403, "admin only")


@app.get("/api/settings/llm")
def get_llm_settings(user: User):
    require_admin(user)
    return {
        "base_url": db.get_setting("llm_base_url") or os.environ.get("TAROT_LLM_BASE_URL", ""),
        "model": db.get_setting("llm_model") or os.environ.get("TAROT_LLM_MODEL", ""),
        "api_key_set": bool(db.get_setting("llm_api_key") or os.environ.get("TAROT_LLM_API_KEY")),
        "from_env": not db.get_setting("llm_base_url") and bool(os.environ.get("TAROT_LLM_BASE_URL")),
    }


@app.put("/api/settings/llm")
def set_llm_settings(req: LlmSettingsRequest, user: User):
    require_admin(user)
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
    return {"reversal_chance": reversal_chance(), "default": DEFAULT_REVERSAL_CHANCE}


@app.put("/api/settings/reading")
def set_reading_settings(req: ReadingSettingsRequest, user: User):
    require_admin(user)
    db.set_setting(
        "reversal_chance",
        "" if req.reversal_chance == DEFAULT_REVERSAL_CHANCE else str(req.reversal_chance),
    )
    return get_reading_settings(user)


class PromptRequest(BaseModel):
    prompt: str = Field(default="", max_length=8000)


@app.get("/api/settings/prompt")
def get_prompt(user: User):
    return {"prompt": db.get_user_prompt(user), "personas": {s: p["prompt"] for s, p in interp.PERSONAS.items()}}


@app.put("/api/settings/prompt")
def set_prompt(req: PromptRequest, user: User):
    db.set_user_prompt(user, req.prompt)
    return {"prompt": db.get_user_prompt(user)}


class SaveReadingRequest(BaseModel):
    deck: str
    spread: str
    question: str | None = None
    cards: list[dict]
    notes: str = ""


class UpdateReadingRequest(BaseModel):
    notes: str | None = None
    shared: bool | None = None


@app.get("/api/readings")
def readings_list(user: User):
    return [{**r, "yours": r["owner"] == user} for r in db.list_readings(user)]


@app.post("/api/readings")
def readings_save(req: SaveReadingRequest, user: User):
    return db.save_reading(user, req.question, req.deck, req.spread, req.cards, notes=req.notes)


@app.get("/api/readings/{reading_id}")
def readings_get(reading_id: int, user: User):
    r = db.get_reading(reading_id, user)
    if not r:
        raise HTTPException(404, "reading not found")
    return {**r, "yours": r["owner"] == user}


@app.patch("/api/readings/{reading_id}")
def readings_update(reading_id: int, req: UpdateReadingRequest, user: User):
    r = db.update_reading(reading_id, user, notes=req.notes, shared=req.shared)
    if not r:
        raise HTTPException(404, "reading not found or not yours")
    return {**r, "yours": True}


@app.delete("/api/readings/{reading_id}")
def readings_delete(reading_id: int, user: User):
    if not db.delete_reading(reading_id, user):
        raise HTTPException(404, "reading not found or not yours")
    return {"deleted": reading_id}


class SpaStaticFiles(StaticFiles):
    """Static files with SPA fallback: unknown paths serve index.html."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


# Serve the built frontend (present in the container; absent in API-only dev).
_static = Path(os.environ.get("TAROT_STATIC_DIR", Path(__file__).parent.parent.parent.parent / "frontend" / "build"))
if _static.is_dir():
    app.mount("/", SpaStaticFiles(directory=_static, html=True), name="frontend")
