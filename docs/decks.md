# Decks: format, downloading, uploading, sharing

## The deck format

A deck is a folder:

```
decks/<slug>/
├── manifest.yaml       # metadata (below)
├── back.jpg            # optional card-back image (any IMAGE_EXT)
└── cards/
    ├── 00.jpg          # canonical index, zero-padded, any of .jpg .jpeg .png .webp .gif
    └── … 77.jpg
```

**Canonical index** (the contract joining images, meanings, and draws):

| Range | Cards |
|---|---|
| 0–21 | Major Arcana, Fool = 0 … World = 21 |
| 22–35 | Wands: ace, 2–10, page, knight, queen, king |
| 36–49 | Cups (same rank order) |
| 50–63 | Swords |
| 64–77 | Pentacles |

`manifest.yaml`:

```yaml
name: Modern Witch Tarot        # display name (required)
source: https://…               # where it came from (optional)
attribution: …                  # credit line (optional)
license: …                      # e.g. "Public domain" (optional)
back: back.jpg                  # card back override (optional; back.* is found automatically)
shared: true                    # user decks only: visible to everyone on the instance
```

**Majors-only decks are supported**: a deck with exactly cards `00`–`21` is
labeled "majors only" and readings draw only from those cards. More generally,
draws only ever use cards the deck actually has; a spread that needs more
cards than the deck holds is rejected.

## Where decks live

| Location | Visibility |
|---|---|
| `decks/` in the image (builtin) | everyone |
| `$TAROT_DATA_DIR/decks/` | everyone on the instance |
| `$TAROT_DATA_DIR/users/<user>/decks/` | that user; everyone if manifest has `shared: true` |

A user's own deck wins slug collisions. Decks are discovered live — drop a
folder in and reload, no restart needed.

## Downloading with tarot-dl

```bash
tarot-dl rws                                              # public-domain Rider–Waite–Smith (Wikimedia)
tarot-dl https://elvitarot.com/decks/tarot/<deck>         # elvitarot adapter
tarot-dl https://www.tarot.com/tarot/decks/<deck>         # tarot.com adapter
tarot-dl https://meliorem.info/cards/<deck>/<any-card>    # meliorem adapter
tarot-dl 'https://example.com/cards/{n}.jpg' --slug my-deck --name 'My Deck'   # generic template
```

The generic template accepts `{n}` (0–77) or `{nn}` (zero-padded). Flags:

| Flag | Purpose |
|---|---|
| `--slug` | deck folder name (default: derived from the URL) |
| `--name` | display name |
| `--user <name>` | download into that user's private collection |
| `--dest <dir>` | explicit decks root (overrides `--user`) |
| `--delay <s>` | seconds between requests (default 0.5 — be polite) |
| `--force` | re-download cards that already exist |
| `--max-width <px>` | downscale images wider than this |

Re-running the same command retries only missing cards, so interrupted or
rate-limited downloads resume safely.

In the container: `docker exec tarot tarot-dl <…>` (data dir defaults to `/data`).

Downloaded decks are for personal use. Buy the physical decks you love.

## Uploading from the browser

Decks page → **Upload a deck**: a zip of card images, landing in your personal
collection.

- **78 images** → full deck, or **22 images** → majors-only; files are assigned
  to the canonical index in alphabetical filename order
- Or number the files `00`–`77` yourself for explicit mapping (any subset works)
- An entry named `back.*` becomes the card back
- Nested folders inside the zip are fine; non-image entries are ignored

## Sharing

- **Decks**: on the Decks page, owners see a share toggle on their decks
  (writes `shared: true` into the manifest). Shared decks appear for every
  user, badged with the owner's name.
- **Readings**: from a journal entry, "Share with instance" makes that reading
  visible (read-only) to other users.
