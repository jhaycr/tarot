import json
import os
import secrets

import httpx
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from tarot import db, interpret as interp
from tarot.auth import current_user
from tarot.cards import CARDS
from tarot.decks import discover_decks, set_deck_shared
from tarot.spreads import SPREADS, SPREADS_BY_SLUG

app = FastAPI(title="Tarotarium", docs_url="/api/docs", openapi_url="/api/openapi.json")

IMAGE_CACHE = {"Cache-Control": "public, max-age=604800"}

MEANINGS: dict[str, dict] = json.loads(
    (Path(__file__).parent.parent / "data" / "meanings.json").read_text()
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
    return {"user": user, "interpretation": interp.config() is not None}


@app.get("/api/cards")
def list_cards():
    out = []
    for c in CARDS:
        m = MEANINGS.get(str(c.index), {})
        out.append({**asdict(c), "upright": m.get("upright"), "reversed_meaning": m.get("reversed")})
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
    path = deck.cards.get(index)
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


@app.post("/api/decks/{slug}/share")
def share_deck(slug: str, req: ShareRequest, user: User):
    deck = get_deck_or_404(slug, user)
    if deck.owner != user:
        raise HTTPException(403, "only the deck's owner can change sharing")
    set_deck_shared(deck, req.shared)
    return {"slug": slug, "shared": req.shared}


@app.get("/api/spreads")
def list_spreads():
    return SPREADS


class DrawRequest(BaseModel):
    deck: str
    spread: str
    reversals: bool = True
    question: str | None = Field(default=None, max_length=500)


@app.post("/api/draw")
def draw(req: DrawRequest, user: User):
    get_deck_or_404(req.deck, user)
    spread = SPREADS_BY_SLUG.get(req.spread)
    if not spread:
        raise HTTPException(404, f"spread '{req.spread}' not found")

    rng = secrets.SystemRandom()
    indices = rng.sample(range(78), len(spread["positions"]))
    drawn = [
        {
            "position": pos,
            "card": asdict(CARDS[i]),
            "reversed": req.reversals and rng.random() < 0.5,
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
