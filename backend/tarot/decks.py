"""Deck discovery: scan deck directories for manifest.yaml + cards/NN.<ext>.

Deck tiers and visibility:
- builtin  decks (shipped in the image)          -> everyone
- library  decks ($TAROT_DATA_DIR/decks)         -> everyone (the shared pool)
- staging  decks ($TAROT_DATA_DIR/users/<u>/decks) -> their owner ONLY

A deck is either a private draft in someone's staging or published to the
shared library — there is no per-person deck sharing. Publishing MOVES the
folder into the library and records `published_by` in its manifest; the move is
a same-filesystem rename, so it is atomic and preserves the dedupe hardlinks.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tarot.cards import MAJORS as MAJOR_NAMES

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

BUILTIN, LIBRARY, STAGING = "builtin", "library", "staging"

# Marker left in `published_by` when a deck's publisher deletes their account
# (Phase 2 / b5): the deck stays in the library but is no longer anyone's to
# unpublish except an admin.
FORMER_MEMBER = "former member"


class DeckConflict(Exception):
    """Target slug already occupied (publish/unpublish would clobber)."""


class DeckForbidden(Exception):
    """Caller may not publish/unpublish this deck."""


def builtin_decks_dir() -> Path:
    # repo root /decks in dev, /app/decks in the container
    return Path(os.environ.get("TAROT_BUILTIN_DECKS", Path(__file__).parent.parent.parent / "decks"))


def data_dir() -> Path:
    return Path(os.environ.get("TAROT_DATA_DIR", Path(__file__).parent.parent.parent / "data"))


def user_decks_dir(user: str | None = None) -> Path:
    if user is None:
        return data_dir() / "decks"
    return data_dir() / "users" / user / "decks"


@dataclass
class Deck:
    slug: str
    path: Path
    name: str
    source: str | None = None
    attribution: str | None = None
    license: str | None = None
    owner: str | None = None  # the staging owner; None for builtin/library
    tier: str = STAGING  # builtin | library | staging
    published_by: str | None = None  # who moved it into the library (library only)
    # optional deck-specific suit names, e.g. {"Wands": "Vitality"}
    suit_names: dict[str, str] = field(default_factory=dict)
    # optional deck-specific major arcana names, e.g. {"The Fool": "Spore"}
    major_names: dict[str, str] = field(default_factory=dict)
    # deck-curated companion guidebooks (book slugs). Only the deck's
    # controller edits this — general books never attach themselves to decks.
    books: list[str] = field(default_factory=list)
    # gallery tile shows the box cover instead of card 0 (owner's choice)
    tile_cover: bool = False
    cards: dict[int, Path] = field(default_factory=dict)
    # deck-specific cards beyond the canonical 78 (e.g. invented majors),
    # addressed as index 78+position: [(index, display name, path), ...]
    extras: list[tuple[int, str, Path]] = field(default_factory=list)
    back: Path | None = None
    cover: Path | None = None  # box/cover art, shown in the gallery but never drawn

    @property
    def complete(self) -> bool:
        return len(self.cards) == 78

    @property
    def majors_only(self) -> bool:
        return len(self.cards) == 22 and all(i < 22 for i in self.cards)

    def image_for(self, index: int) -> Path | None:
        if index < 78:
            return self.cards.get(index)
        for i, _, path in self.extras:
            if i == index:
                return path
        return None


def _load_deck(deck_path: Path, owner: str | None = None, tier: str = STAGING) -> Deck | None:
    manifest_path = deck_path / "manifest.yaml"
    if not manifest_path.is_file():
        return None
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    deck = Deck(
        slug=deck_path.name,
        path=deck_path,
        name=manifest.get("name", deck_path.name),
        source=manifest.get("source"),
        attribution=manifest.get("attribution"),
        license=manifest.get("license"),
        owner=owner,
        tier=tier,
        published_by=manifest.get("published_by") if tier == LIBRARY else None,
        suit_names={
            k: str(v)
            for k, v in (manifest.get("suits") or {}).items()
            if k in ("Wands", "Cups", "Swords", "Pentacles") and v
        },
        major_names={
            k: str(v)
            for k, v in (manifest.get("majors") or {}).items()
            if k in MAJOR_NAMES and v
        },
        books=[str(b) for b in manifest.get("books") or [] if b],
        tile_cover=bool(manifest.get("tile_cover")),
    )
    cards_dir = deck_path / "cards"
    if cards_dir.is_dir():
        for f in cards_dir.iterdir():
            if f.suffix.lower() not in IMAGE_EXTS:
                continue
            stem = f.stem
            if stem.isdigit() and 0 <= int(stem) <= 77:
                deck.cards[int(stem)] = f
    extras_dir = deck_path / "extras"
    if extras_dir.is_dir():
        names = manifest.get("extras") or {}  # optional {file-stem: display name}
        files = sorted(
            f for f in extras_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )
        deck.extras = [
            (78 + i, names.get(f.stem) or f.stem.replace("-", " ").replace("_", " ").title(), f)
            for i, f in enumerate(files)
        ]
    for attr in ("back", "cover"):
        named = manifest.get(attr)
        if named and (deck_path / named).is_file():
            setattr(deck, attr, deck_path / named)
            continue
        for ext in IMAGE_EXTS:
            candidate = deck_path / f"{attr}{ext}"
            if candidate.is_file():
                setattr(deck, attr, candidate)
                break
    return deck


def _scan(root: Path, owner: str | None = None, tier: str = STAGING) -> list[Deck]:
    if not root.is_dir():
        return []
    decks = []
    for deck_path in sorted(root.iterdir()):
        if deck_path.is_dir():
            deck = _load_deck(deck_path, owner=owner, tier=tier)
            if deck and deck.cards:
                decks.append(deck)
    return decks


def all_users() -> list[str]:
    users_root = data_dir() / "users"
    if not users_root.is_dir():
        return []
    return sorted(p.name for p in users_root.iterdir() if p.is_dir())


def discover_decks(user: str | None = None) -> dict[str, Deck]:
    """Decks visible to `user` (or only the public pool when user is None).

    builtin + library are visible to everyone; a user additionally sees their
    own private staging. Later sources win on slug collision, so a staging draft
    shadows a library deck of the same slug for its owner.
    """
    decks: dict[str, Deck] = {}
    for deck in _scan(builtin_decks_dir(), tier=BUILTIN):
        decks[deck.slug] = deck
    for deck in _scan(user_decks_dir(None), tier=LIBRARY):
        decks[deck.slug] = deck
    if user is not None:
        for deck in _scan(user_decks_dir(user), owner=user, tier=STAGING):
            decks[deck.slug] = deck
    return decks


def update_manifest(deck_path: Path, **changes) -> None:
    """Merge `changes` into a deck's manifest.yaml; a value of None drops its key."""
    manifest_path = deck_path / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    for key, value in changes.items():
        if value is None:
            manifest.pop(key, None)
        else:
            manifest[key] = value
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))


def publish_deck(user: str, slug: str, now: int) -> Deck | None:
    """Move `user`'s staging deck into the shared library.

    Returns None if `user` has no such staging deck (caller -> 404); raises
    DeckConflict if the library slug is taken.
    """
    src = user_decks_dir(user) / slug
    if not (src / "manifest.yaml").is_file():
        return None
    dest = user_decks_dir(None) / slug
    if dest.exists():
        raise DeckConflict(slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)  # same filesystem: atomic, keeps dedupe hardlinks
    update_manifest(dest, published_by=user, published_at=now, shared=None)
    return _load_deck(dest, tier=LIBRARY)


def unpublish_deck(user: str, slug: str, is_admin: bool, now: int) -> Deck | None:
    """Move a library deck back into its publisher's staging.

    Returns None if there is no such library deck (caller -> 404); raises
    DeckForbidden if `user` is neither the publisher nor an admin, and
    DeckConflict if the publisher already has a staging deck of that slug.
    """
    src = user_decks_dir(None) / slug
    manifest_path = src / "manifest.yaml"
    if not manifest_path.is_file():
        return None
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    publisher = manifest.get("published_by")
    if not is_admin and publisher != user:
        raise DeckForbidden(slug)
    # A tombstoned/unknown publisher can't receive it back; the acting admin does.
    target = publisher if publisher and publisher != FORMER_MEMBER else user
    dest = user_decks_dir(target) / slug
    if dest.exists():
        raise DeckConflict(slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    update_manifest(dest, published_by=None, published_at=None)
    return _load_deck(dest, owner=target, tier=STAGING)


def delete_deck(user: str, slug: str) -> bool:
    """Delete `user`'s staging draft outright. Returns False if there is no
    such draft (caller -> 404). Builtin and library decks are never touched —
    a published deck must be unpublished back to a draft first, which also
    keeps deletion scoped to folders under the caller's own staging dir.
    """
    target = user_decks_dir(user) / slug
    if not (target / "manifest.yaml").is_file():
        return False
    shutil.rmtree(target)
    return True


def migrate_publish_decks(now: int) -> tuple[list[str], list[str]]:
    """One-time migration: move every deck that was shared under the old flag —
    plus everything the system user (`local`) staged — into the shared library.

    `local` is a shared LAN pseudo-user with no privacy expectation, so all of
    its decks are published; other users only have their explicitly `shared`
    decks moved. Idempotent and defensive: a deck whose library slug is already
    taken, or that fails to move, is skipped rather than aborting the batch.

    Returns (published, skipped) as human-readable "<owner>/<slug>" lists.
    """
    from tarot.auth import FALLBACK_USER

    library = user_decks_dir(None)
    published: list[str] = []
    skipped: list[str] = []
    for owner in all_users():
        staging = user_decks_dir(owner)
        if not staging.is_dir():
            continue
        for deck_path in sorted(p for p in staging.iterdir() if p.is_dir()):
            manifest_path = deck_path / "manifest.yaml"
            if not manifest_path.is_file():
                continue
            try:
                manifest = yaml.safe_load(manifest_path.read_text()) or {}
            except yaml.YAMLError:
                skipped.append(f"{owner}/{deck_path.name} (unreadable manifest)")
                continue
            if owner != FALLBACK_USER and not manifest.get("shared"):
                continue  # another user's private draft stays put
            dest = library / deck_path.name
            if dest.exists():
                skipped.append(f"{owner}/{deck_path.name} (library slug taken)")
                continue
            try:
                library.mkdir(parents=True, exist_ok=True)
                deck_path.rename(dest)
                update_manifest(dest, published_by=owner, published_at=now, shared=None)
                published.append(f"{owner}/{deck_path.name}")
            except OSError as exc:
                skipped.append(f"{owner}/{deck_path.name} ({exc})")
    return published, skipped
