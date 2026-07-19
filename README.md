# Arcana — self-hosted tarot

Multi-deck tarot reader: draws and spreads, card meanings, a reading journal,
optional LLM interpretation, and a deck downloader (`tarot-dl`). Ships as a
single container: FastAPI backend + SvelteKit static PWA frontend.

## Layout

- `backend/` — Python package `tarot`: API (`tarot.api.app`), downloader (`tarot-dl`)
- `frontend/` — SvelteKit SPA (adapter-static), built into `frontend/build`
- `decks/` — bundled decks (each: `manifest.yaml` + `cards/00..77.jpg`)
- Runtime data lives in `$TAROT_DATA_DIR` (default `./data`, container `/data`):
  user decks in `decks/`, journal SQLite alongside

## Deck format

```
decks/<slug>/
├── manifest.yaml       # name, source, attribution, license, back (optional)
└── cards/00.jpg…77.jpg # canonical order: 0–21 majors, then wands, cups, swords, pentacles
```

Canonical index is the contract joining deck images, meanings, and draws.
Any deck folder with a manifest is picked up automatically.

## Development

```bash
# backend
cd backend && uv venv && uv pip install -e . && .venv/bin/uvicorn tarot.api.app:app --reload

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

## Container

```bash
docker build -t tarot .
docker run -p 8000:8000 -v ./data:/data tarot
```

## Downloading decks

```bash
tarot-dl <deck-page-url>          # site adapter chosen by domain
tarot-dl --template 'https://example.com/deck/{n}.jpg' --slug my-deck --name 'My Deck'
```

Downloaded decks are for personal use; respect the artists — buy the physical
decks you love.
