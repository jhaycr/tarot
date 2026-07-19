# Decks: format, downloading, uploading, sharing

## The deck format

A deck is a folder:

```
decks/<slug>/
├── manifest.yaml       # metadata (below)
├── back.jpg            # optional card-back image (any IMAGE_EXT)
├── cards/
│   ├── 00.jpg          # canonical index, zero-padded, any of .jpg .jpeg .png .webp .gif
│   └── … 77.jpg
└── extras/             # optional deck-specific cards beyond the 78 (see Extras)
    └── the-happy-squirrel.jpg
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

**Extras**: some decks invent cards beyond the canonical 78 (additional majors,
artist cards). Put their images in an `extras/` folder — filenames become the
display names (`the-happy-squirrel.jpg` → "The Happy Squirrel"), overridable via
`extras: {file-stem: Display Name}` in the manifest. Extras appear in their own
deck-gallery section and join draws only when the querent opts in per deck on
the reading setup page. They have no canonical meanings, and readings containing
them can't be re-skinned with other decks. Zips and folder imports pick up an
`extras/` folder automatically.

## Where decks live

| Location | Visibility |
|---|---|
| `decks/` in the image (builtin) | everyone |
| `$TAROT_DATA_DIR/decks/` | everyone on the instance |
| `$TAROT_DATA_DIR/users/<user>/decks/` | that user; everyone if manifest has `shared: true` |

A user's own deck wins slug collisions. Decks are discovered live — drop a
folder in and reload, no restart needed.

**Storage dedupe**: identical card images across decks (e.g. the same deck
downloaded by several users) are stored once under `$TAROT_DATA_DIR/objects/`
(content-addressed by SHA-256) and hardlinked into each deck folder. This
happens automatically after downloads/uploads and at startup; deleting a deck
never affects another, and unreferenced objects are pruned.

## Downloading with tarot-dl

```bash
tarot-dl rws                                              # public-domain Rider–Waite–Smith (Wikimedia)
tarot-dl marseille                                        # Jean Dodal Tarot de Marseille trumps (majors-only)
tarot-dl https://elvitarot.com/decks/tarot/<deck>         # elvitarot adapter
tarot-dl https://www.tarot.com/tarot/decks/<deck>         # tarot.com adapter
tarot-dl https://meliorem.info/cards/<deck>/<any-card>    # meliorem adapter
tarot-dl 'https://example.com/cards/{n}.jpg' --slug my-deck --name 'My Deck'   # generic template
tarot-dl ~/Pictures/Tarot/MyDeck --name 'My Deck'         # local folder import (naming below)
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
collection. Filenames are mapped to the canonical index by recognizing any mix
of these styles (`tarot-dl <folder>` imports use the same rules):

| Style | Examples | Notes |
|---|---|---|
| Canonical numeric | `00.jpg` … `77.jpg` | authoritative |
| Named | `00-Major-Fool.jpg`, `23-Minor-Discs-02.jpg` | mapped by **name**, so Marseilles trump order (Justice VIII) and any suit order land correctly; the leading number is ignored |
| Commons-style | `Wands01.jpg` … `Wands14.jpg`, `Coins07.jpg`, `RWS_Tarot_08_Strength.jpg` | `01`=ace … `10`, `11`–`14`=page/knight/queen/king |
| 1-based numeric | `Card01.jpg` … `Card78.jpg` | detected when there's no card 0; `01` becomes The Fool |

- Suit synonyms: batons/staves/rods→wands, chalices→cups, discs/coins/deniers→pentacles
- Court synonyms: knave/princess/valet→page, prince/cavalier→knight
- `back.*`/`*reverse*` becomes the card back; `*box*`/`*cover*` files are ignored
- 78 recognized images → full deck; exactly the 22 majors → majors-only; partial
  decks are accepted when every file is recognized
- If nothing is recognizable but the zip holds exactly 78 (or 22) images, they're
  assigned in alphabetical order as a fallback
- Nested folders inside the zip are fine; non-image entries are ignored

## Sharing

- **Decks**: on the Decks page, owners see a share toggle on their decks
  (writes `shared: true` into the manifest). Shared decks appear for every
  user, badged with the owner's name.
- **Readings**: from a journal entry, "Share with instance" makes that reading
  visible (read-only) to other users.
