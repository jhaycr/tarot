# Tarotarium — self-hosted tarot

*A planetarium for the cards: seventy-eight small skies to sit under.*

Multi-deck tarot reader for your homelab: draws and spreads, card meanings,
a reading journal, multi-user support behind an authenticating proxy, optional
LLM interpretation with selectable reader personas, and a deck downloader
(`tarot-dl`). Ships as a single container: FastAPI backend + SvelteKit PWA
frontend (installable on phones, offline-capable).

## 🤖 An AI-native project

This project was designed and built **AI-natively**: the architecture, code,
tests, card meanings, icons, and this README were produced by
[Claude Code](https://claude.com/claude-code) (Claude Fable 5) working in
conversation with the project owner, who directed the design, made the product
decisions, and reviewed the results. Expect the codebase to read like it was
written for AI collaboration — small modules, a single canonical data contract,
and plain-language docs — because it was. AI is also part of the product: the
optional interpretation feature sends readings to an LLM endpoint you configure,
with personas you can edit or replace.

## Features

- **Readings** — single, three-card, and Celtic Cross spreads; tap-to-flip
  cards; optional reversals; server-side CSPRNG shuffles
- **Decks** — drop-in deck folders; bundled public-domain Rider–Waite–Smith
  (1909 scans via Wikimedia Commons); per-user decks with instance sharing
- **Meanings** — upright and reversed keywords for all 78 cards
- **Journal** — save readings with notes; share individual readings with other
  users on your instance
- **Multi-user** — trusts the username header injected by an authenticating
  reverse proxy (authentik proxy provider or similar); falls back to a single
  `local` user without one
- **LLM interpretation** (optional) — any OpenAI-compatible endpoint; choose a
  reader persona per reading: Alice (secular, psychology-first), Selene
  (spiritualist), or your own custom system prompt
- **PWA** — add to home screen, offline app shell, cached card images

## Layout

- `backend/` — Python package `tarot`: API (`tarot.api.app`), downloader (`tarot-dl`)
- `frontend/` — SvelteKit SPA (adapter-static), built into `frontend/build`
- `decks/` — bundled decks (each: `manifest.yaml` + `cards/00..77.jpg`)
- Runtime data lives in `$TAROT_DATA_DIR` (default `./data`, container `/data`):
  instance decks in `decks/`, per-user decks in `users/<name>/decks/`,
  journal + settings in `journal.db`

## Deck format

```
decks/<slug>/
├── manifest.yaml       # name, source, attribution, license, back (optional), shared (optional)
└── cards/00.jpg…77.jpg # canonical order: 0–21 majors, then wands, cups, swords, pentacles
```

The canonical 0–77 index (minors: ace, 2–10, page, knight, queen, king per
suit) is the contract joining deck images, meanings, and draws. Any deck folder
with a manifest is picked up automatically.

## Downloading decks

```bash
tarot-dl rws                                  # bundled-source Rider–Waite–Smith
tarot-dl <deck-page-url>                      # site adapter chosen by domain
tarot-dl <url> --user josh                    # into one user's private collection
tarot-dl --slug my-deck 'https://example.com/deck/{n}.jpg'   # generic URL template
```

Downloaded decks are for personal use; respect the artists — buy the physical
decks you love.

## Configuration

| Env var | Purpose |
|---|---|
| `TAROT_DATA_DIR` | data root (container default `/data`) |
| `TAROT_AUTH_HEADER` | trusted username header (default `x-authentik-username`) |
| `TAROT_LLM_BASE_URL` | OpenAI-compatible endpoint; unset disables interpretation |
| `TAROT_LLM_MODEL` / `TAROT_LLM_API_KEY` | model name / optional bearer token |
| `TAROT_LLM_SYSTEM_PROMPT` | instance-wide default persona override |

## Development

```bash
# backend
cd backend && uv venv && uv pip install -e . && .venv/bin/uvicorn tarot.api.app:app --reload

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

## Container

```bash
docker build -t tarotarium .
docker run -p 8000:8000 -v ./data:/data tarotarium
```

## License

[MIT](LICENSE). Bundled Rider–Waite–Smith card images are public domain
(Pamela Colman Smith, 1909; scans via Wikimedia Commons). The default "Alice"
persona prompt is adapted from the project owner's own prompt library.
