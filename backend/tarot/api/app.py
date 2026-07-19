import os
import secrets
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from tarot.cards import CARDS
from tarot.decks import discover_decks
from tarot.spreads import SPREADS, SPREADS_BY_SLUG

app = FastAPI(title="tarot", docs_url="/api/docs", openapi_url="/api/openapi.json")

IMAGE_CACHE = {"Cache-Control": "public, max-age=604800"}


def get_deck_or_404(slug: str):
    deck = discover_decks().get(slug)
    if not deck:
        raise HTTPException(404, f"deck '{slug}' not found")
    return deck


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/cards")
def list_cards():
    return [asdict(c) for c in CARDS]


@app.get("/api/decks")
def list_decks():
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
        }
        for d in discover_decks().values()
    ]


@app.get("/api/decks/{slug}/cards/{index}")
def card_image(slug: str, index: int):
    deck = get_deck_or_404(slug)
    path = deck.cards.get(index)
    if not path:
        raise HTTPException(404, f"card {index} missing from deck '{slug}'")
    return FileResponse(path, headers=IMAGE_CACHE)


@app.get("/api/decks/{slug}/back")
def back_image(slug: str):
    deck = get_deck_or_404(slug)
    if not deck.back:
        raise HTTPException(404, f"deck '{slug}' has no back image")
    return FileResponse(deck.back, headers=IMAGE_CACHE)


@app.get("/api/spreads")
def list_spreads():
    return SPREADS


class DrawRequest(BaseModel):
    deck: str
    spread: str
    reversals: bool = True
    question: str | None = Field(default=None, max_length=500)


@app.post("/api/draw")
def draw(req: DrawRequest):
    deck = get_deck_or_404(req.deck)
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
