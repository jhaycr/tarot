# Tarotarium — self-hosted tarot

*A planetarium for the cards: seventy-eight small skies to sit under.*

Multi-deck tarot reader for your homelab: draws and spreads, card meanings,
guided card-by-card readings, a journal, a shared deck library, multi-user
support behind an authenticating proxy, optional LLM interpretation with
selectable reader personas, and a deck downloader (`tarot-dl`). Ships as a
single container: FastAPI backend + SvelteKit PWA frontend (installable on
phones, offline-capable).

> **Personal project, no support.** Built largely with AI code-generation tools
> to scratch my own itch. Shared in case it's useful to you too. Issues and
> feature requests are welcome and I read them all, but responses and fixes
> happen on hobby-project time. Review and test before relying on it.

## 🤖 An AI-native project

This project was designed and built **AI-natively**: the architecture, code,
tests, card meanings, icons, and this README were produced by
[Claude Code](https://claude.com/claude-code) working in conversation with the
project owner, who directed the design, made the product decisions, and
reviewed the results. Expect the codebase to read like it was written for AI
collaboration — small modules, a single canonical data contract, and
plain-language docs — because it was. AI is also part of the product: the
optional interpretation feature sends readings to an LLM endpoint you
configure, with personas you can edit or replace.

## Quick start

```yaml
# docker-compose.yml
services:
  tarot:
    image: ghcr.io/jhaycr/tarot:latest
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data          # decks, journal DB, settings — everything lives here
    environment:
      # optional — enables AI interpretation; see Configuration for the rest
      TAROT_LLM_BASE_URL: https://openrouter.ai/api/v1
      TAROT_LLM_MODEL: minimax/minimax-m2
      TAROT_LLM_API_KEY: your-key-here
    restart: unless-stopped
```

`docker compose up -d`, open <http://localhost:8000>, and you're reading as the
built-in `local` user with the bundled Rider–Waite–Smith deck. For multiple
users, put the app behind an authenticating reverse proxy (authentik proxy
provider or similar) that injects a username header — see Configuration.

To build and run from source instead:

```bash
docker build -t tarotarium .
docker run -p 8000:8000 -v ./data:/data tarotarium
```

## Features

- **Readings** — single, three-card, and Celtic Cross spreads; tap-to-flip
  cards; optional reversals; server-side CSPRNG shuffles; full-art lightbox
  with keywords and Waite's meanings on every revealed card
- **Guided readings** — an LLM reads each card as you flip it (streamed live),
  then draws the whole spread together; resumable mid-reading, saved to the
  journal
- **Meanings** — upright and reversed keywords for all 78 cards, plus the full
  divinatory meanings from A. E. Waite's *Pictorial Key to the Tarot* (1911,
  public domain, via Wikisource)
- **Journal** — save readings with notes; per-reading visibility (private,
  specific people, or everyone on the instance); re-view any reading with a
  different deck's art
- **Decks** — drop-in deck folders; bundled public-domain Rider–Waite–Smith
  (1909 scans via Wikimedia Commons); private drafts you can publish to a
  shared library; zip upload/export; per-deck suit and card renames;
  deck-specific extra cards beyond the canonical 78
- **Deck tooling** — `tarot-dl` downloads decks by URL (site adapters, Fandom
  wikis, Wayback Machine snapshots, URL templates, local folders); `tarot-slice`
  cuts card sheets, photos, and printable PDFs into individual cards
- **Multi-user** — trusts the username header injected by an authenticating
  reverse proxy; falls back to a single `local` user without one; admin page
  for renaming/deactivating users
- **LLM interpretation** (optional) — any OpenAI-compatible endpoint
  (OpenRouter, OpenAI, Ollama…); configure in Settings as an admin (API key
  encrypted at rest), via env vars, or declaratively for config-managed
  instances; choose a reader persona per reading: Alice (secular,
  psychology-first), Selene (spiritualist), or your own custom system prompt
- **Spoken readings** (optional) — interpretations read aloud in a voice that
  matches the persona, via any OpenAI-compatible `/audio/speech` endpoint
  (OpenAI `gpt-4o-mini-tts` with per-persona style instructions, or free
  self-hosted [Kokoro](https://github.com/remsky/Kokoro-FastAPI)); play button
  on every reading plus an auto-read mode; audio cached server-side under a
  configurable disk budget
- **PWA** — add to home screen, offline app shell, cached card images

## Configuration

| Env var | Purpose |
|---|---|
| `TAROT_DATA_DIR` | data root (container default `/data`) |
| `TAROT_AUTH_HEADER` | trusted username header (default `x-authentik-username`) |
| `TAROT_LLM_BASE_URL` | OpenAI-compatible endpoint (e.g. `https://openrouter.ai/api/v1`); unset everywhere disables interpretation |
| `TAROT_LLM_MODEL` / `TAROT_LLM_API_KEY` | model name (e.g. `minimax/minimax-m2`) / optional bearer token |
| `TAROT_LLM_SYSTEM_PROMPT` | instance-wide default persona override |
| `TAROT_TTS_BASE_URL` | OpenAI-compatible TTS endpoint (e.g. `https://api.openai.com/v1`, or a Kokoro container's `http://kokoro:8880/v1`); unset everywhere disables spoken readings |
| `TAROT_TTS_MODEL` / `TAROT_TTS_API_KEY` | TTS model (default `gpt-4o-mini-tts`; Kokoro: `kokoro`) / optional bearer token |
| `TAROT_ADMIN_USERS` | comma-separated users who may edit instance settings (default: the fallback user) |
| `TAROT_SECRET_KEY` | Fernet key for credential encryption (default: auto-generated at `/data/.secret_key`) |

For Ansible/GitOps-managed instances, `/data/config.yaml` sets the same knobs
declaratively (LLM + TTS connections, per-persona voices, reversal chance,
default persona); file-managed fields show read-only in the Settings UI.
Precedence: config file → admin Settings → env vars.

Self-hosting the voice: run a
[Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) container next to
the app (`ghcr.io/remsky/kokoro-fastapi-cpu`, CPU is enough) and point the TTS
base URL at it with model `kokoro` and a voice like `af_heart` — no API key or
cloud account needed. Voice style instructions only apply on endpoints that
support them (OpenAI).

## Decks

```
decks/<slug>/
├── manifest.yaml       # name, source, attribution, license, back, suit/major renames, extras
├── cards/00.jpg…77.jpg # canonical order: 0–21 majors, then wands, cups, swords, pentacles
└── extras/             # optional deck-specific cards beyond the canonical 78
```

The canonical 0–77 index (minors: ace, 2–10, page, knight, queen, king per
suit) is the contract joining deck images, meanings, and draws. Any deck folder
with a manifest is picked up automatically; partial and majors-only decks work.

```bash
tarot-dl rws                                  # bundled-source Rider–Waite–Smith
tarot-dl <deck-page-url>                      # site adapter chosen by domain (incl. Fandom wikis)
tarot-dl 'http://web.archive.org/web/<ts>/<gallery-url>'     # dead-site galleries via Wayback
tarot-dl --slug my-deck 'https://example.com/deck/{n}.jpg'   # generic URL template
tarot-dl <url> --user josh                    # into one user's private drafts
```

Downloaded decks are for personal use; respect the artists — buy the physical
decks you love. Full deck how-to (format, importing, uploads, publishing):
[docs/decks.md](docs/decks.md).

## Layout

- `backend/` — Python package `tarot`: API (`tarot.api.app`), downloader
  (`tarot-dl`), slicer (`tarot-slice`, needs the `[slice]` extra)
- `frontend/` — SvelteKit SPA (adapter-static), built into `frontend/build`
- `decks/` — bundled decks
- Runtime data lives in `$TAROT_DATA_DIR` (default `./data`, container `/data`):
  the shared deck library in `decks/`, per-user drafts in `users/<name>/decks/`,
  journal + settings in `journal.db` (schema-versioned, auto-migrating with a
  pre-migration backup)

## Development

```bash
# backend
cd backend && uv venv && uv pip install -e . && .venv/bin/uvicorn tarot.api.app:app --reload

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

## License

[MIT](LICENSE). Bundled Rider–Waite–Smith card images are public domain
(Pamela Colman Smith, 1909; scans via Wikimedia Commons). The default "Alice"
persona prompt is adapted from the project owner's own prompt library.
