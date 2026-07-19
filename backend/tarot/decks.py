"""Deck discovery: scan deck directories for manifest.yaml + cards/NN.<ext>."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def builtin_decks_dir() -> Path:
    # repo root /decks in dev, /app/decks in the container
    return Path(os.environ.get("TAROT_BUILTIN_DECKS", Path(__file__).parent.parent.parent / "decks"))


def data_dir() -> Path:
    return Path(os.environ.get("TAROT_DATA_DIR", Path(__file__).parent.parent.parent / "data"))


def user_decks_dir() -> Path:
    return data_dir() / "decks"


@dataclass
class Deck:
    slug: str
    path: Path
    name: str
    source: str | None = None
    attribution: str | None = None
    license: str | None = None
    cards: dict[int, Path] = field(default_factory=dict)
    back: Path | None = None

    @property
    def complete(self) -> bool:
        return len(self.cards) == 78


def _load_deck(deck_path: Path) -> Deck | None:
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
    )
    cards_dir = deck_path / "cards"
    if cards_dir.is_dir():
        for f in cards_dir.iterdir():
            if f.suffix.lower() not in IMAGE_EXTS:
                continue
            stem = f.stem
            if stem.isdigit() and 0 <= int(stem) <= 77:
                deck.cards[int(stem)] = f
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


def discover_decks() -> dict[str, Deck]:
    """User decks shadow builtin decks with the same slug."""
    decks: dict[str, Deck] = {}
    for root in (builtin_decks_dir(), user_decks_dir()):
        if not root.is_dir():
            continue
        for deck_path in sorted(root.iterdir()):
            if not deck_path.is_dir():
                continue
            deck = _load_deck(deck_path)
            if deck and deck.cards:
                decks[deck.slug] = deck
    return decks
