"""Canonical 78-card index shared by decks, meanings, draws, and the downloader.

Index layout: 0-21 majors, 22-35 wands, 36-49 cups, 50-63 swords, 64-77 pentacles.
Minor arcana rank order within each suit: ace, 2-10, page, knight, queen, king.
"""

from dataclasses import dataclass

MAJORS = [
    "The Fool", "The Magician", "The High Priestess", "The Empress",
    "The Emperor", "The Hierophant", "The Lovers", "The Chariot",
    "Strength", "The Hermit", "Wheel of Fortune", "Justice",
    "The Hanged Man", "Death", "Temperance", "The Devil",
    "The Tower", "The Star", "The Moon", "The Sun",
    "Judgement", "The World",
]

SUITS = ["Wands", "Cups", "Swords", "Pentacles"]

RANKS = [
    "Ace", "Two", "Three", "Four", "Five", "Six", "Seven",
    "Eight", "Nine", "Ten", "Page", "Knight", "Queen", "King",
]


@dataclass(frozen=True)
class Card:
    index: int
    name: str
    arcana: str  # "major" | "minor"
    suit: str | None = None
    rank: str | None = None
    number: int | None = None  # major arcana number, or rank number 1-14


def _build() -> list[Card]:
    cards = [
        Card(index=i, name=name, arcana="major", number=i)
        for i, name in enumerate(MAJORS)
    ]
    for s, suit in enumerate(SUITS):
        for r, rank in enumerate(RANKS):
            cards.append(Card(
                index=22 + s * 14 + r,
                name=f"{rank} of {suit}",
                arcana="minor",
                suit=suit,
                rank=rank,
                number=r + 1,
            ))
    return cards


CARDS: list[Card] = _build()
assert len(CARDS) == 78
