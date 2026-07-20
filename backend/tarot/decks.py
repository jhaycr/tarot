"""Deck discovery: scan deck directories for manifest.yaml + cards/NN.<ext>.

Deck locations and visibility:
- builtin decks (shipped in the image)          -> everyone
- instance decks  ($TAROT_DATA_DIR/decks)       -> everyone
- user decks      ($TAROT_DATA_DIR/users/<u>/decks)
    -> their owner always; others only when the manifest has `shared: true`
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tarot.cards import MAJORS as MAJOR_NAMES

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


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
    owner: str | None = None  # None = builtin/instance deck, visible to all
    shared: bool = False
    # optional deck-specific suit names, e.g. {"Wands": "Vitality"}
    suit_names: dict[str, str] = field(default_factory=dict)
    # optional deck-specific major arcana names, e.g. {"The Fool": "Spore"}
    major_names: dict[str, str] = field(default_factory=dict)
    cards: dict[int, Path] = field(default_factory=dict)
    # deck-specific cards beyond the canonical 78 (e.g. invented majors),
    # addressed as index 78+position: [(index, display name, path), ...]
    extras: list[tuple[int, str, Path]] = field(default_factory=list)
    back: Path | None = None

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


def _load_deck(deck_path: Path, owner: str | None = None) -> Deck | None:
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
        shared=bool(manifest.get("shared")),
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
    back_name = manifest.get("back")
    if back_name and (deck_path / back_name).is_file():
        deck.back = deck_path / back_name
    else:
        for ext in IMAGE_EXTS:
            candidate = deck_path / f"back{ext}"
            if candidate.is_file():
                deck.back = candidate
                break
    return deck


def _scan(root: Path, owner: str | None = None) -> list[Deck]:
    if not root.is_dir():
        return []
    decks = []
    for deck_path in sorted(root.iterdir()):
        if deck_path.is_dir():
            deck = _load_deck(deck_path, owner=owner)
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

    Later sources win on slug collision; a user's own deck always wins last.
    """
    decks: dict[str, Deck] = {}
    for deck in _scan(builtin_decks_dir()) + _scan(user_decks_dir(None)):
        decks[deck.slug] = deck
    if user is not None:
        for other in all_users():
            if other == user:
                continue
            for deck in _scan(user_decks_dir(other), owner=other):
                if deck.shared:
                    decks[deck.slug] = deck
        for deck in _scan(user_decks_dir(user), owner=user):
            decks[deck.slug] = deck
    return decks


def set_deck_shared(deck: Deck, shared: bool) -> None:
    manifest_path = deck.path / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    manifest["shared"] = shared
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))
