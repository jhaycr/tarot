"""Guidebook discovery: scan book directories for manifest.yaml.

Book tiers mirror decks, minus builtin — book text is copyrighted and lives
only under gitignored /data, never in the image:
- library  books ($TAROT_DATA_DIR/books)           -> everyone (shared pool)
- staging  books ($TAROT_DATA_DIR/users/<u>/books) -> their owner ONLY

A book folder holds the original source.pdf, rendered pages/NNN.webp, the
full segmented text (chunks.json — the ENTIRE book, card-keyed where it maps
and topic-tagged elsewhere), a derived per-card view (cards.json keyed
"0".."77"), and manifest.yaml — written LAST by the importer, so its
presence means the import completed (a crashed import is invisible and can
be re-run or deleted).

Publishing MOVES the folder into the library via a same-filesystem rename
(atomic), recording `published_by`, exactly like decks.
"""

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tarot.decks import FORMER_MEMBER, LIBRARY, STAGING, data_dir, update_manifest

PAGE_EXT = ".webp"


class BookConflict(Exception):
    """Target slug already occupied (publish/unpublish would clobber)."""


class BookForbidden(Exception):
    """Caller may not publish/unpublish this book."""


def user_books_dir(user: str | None = None) -> Path:
    if user is None:
        return data_dir() / "books"
    return data_dir() / "users" / user / "books"


@dataclass
class Book:
    slug: str
    path: Path
    name: str
    author: str | None = None
    source: str | None = None
    attribution: str | None = None
    license: str | None = None
    owner: str | None = None  # the staging owner; None for library
    tier: str = STAGING  # library | staging
    published_by: str | None = None
    pages: int = 0
    cards_covered: int = 0
    chunk_count: int = 0
    extractor: int = 0
    llm_assisted: bool = False

    def page_image(self, n: int) -> Path | None:
        p = self.path / "pages" / f"{n:03d}{PAGE_EXT}"
        return p if p.is_file() else None

    def card_pages(self) -> dict[int, int]:
        """Jump-nav target page (0-based) per covered card index: the first
        page of the card's PRIMARY passage — longest non-index-like entry —
        not the minimum over every match, which would send jumps to the
        card's contents/index mention at the front of the book."""
        try:
            cards = json.loads((self.path / "cards.json").read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        out: dict[int, int] = {}
        for key, passages in cards.items():
            real = [e for e in passages
                    if e.get("pages") and not _index_like(e.get("text", ""))]
            pool = real or [e for e in passages if e.get("pages")]
            if pool:
                rank = {"toc": 0, "contents": 1}
                primary = min(pool, key=lambda e: (rank.get(e.get("source"), 2),
                                                   0 if e.get("primary") else 1,
                                                   -len(e.get("text", ""))))
                out[int(key)] = min(primary["pages"])
        return out


def _load_book(book_path: Path, owner: str | None = None, tier: str = STAGING) -> Book | None:
    manifest_path = book_path / "manifest.yaml"
    if not manifest_path.is_file():
        return None
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    return Book(
        slug=book_path.name,
        path=book_path,
        name=manifest.get("name", book_path.name),
        author=manifest.get("author"),
        source=manifest.get("source"),
        attribution=manifest.get("attribution"),
        license=manifest.get("license"),
        owner=owner,
        tier=tier,
        published_by=manifest.get("published_by") if tier == LIBRARY else None,
        pages=int(manifest.get("pages") or 0),
        cards_covered=int(manifest.get("cards_covered") or 0),
        chunk_count=int(manifest.get("chunk_count") or 0),
        extractor=int(manifest.get("extractor") or 0),
        llm_assisted=bool(manifest.get("llm_assisted")),
    )


def _scan(root: Path, owner: str | None = None, tier: str = STAGING) -> list[Book]:
    if not root.is_dir():
        return []
    books = []
    for book_path in sorted(root.iterdir()):
        if book_path.is_dir():
            book = _load_book(book_path, owner=owner, tier=tier)
            if book:
                books.append(book)
    return books


def discover_books(user: str | None = None) -> dict[str, Book]:
    """Books visible to `user`: the shared library, plus their own staging.
    Later wins on slug collision, so a staging draft shadows a library book
    of the same slug for its owner (same rule as decks)."""
    books: dict[str, Book] = {}
    for book in _scan(user_books_dir(None), tier=LIBRARY):
        books[book.slug] = book
    if user is not None:
        for book in _scan(user_books_dir(user), owner=user, tier=STAGING):
            books[book.slug] = book
    return books


def publish_book(user: str, slug: str, now: int) -> Book | None:
    """Move `user`'s staging book into the shared library. Returns None if
    there is no such (completed) staging book; raises BookConflict if the
    library slug is taken."""
    src = user_books_dir(user) / slug
    if not (src / "manifest.yaml").is_file():
        return None
    dest = user_books_dir(None) / slug
    if dest.exists():
        raise BookConflict(slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)  # same filesystem: atomic
    update_manifest(dest, published_by=user, published_at=now)
    return _load_book(dest, tier=LIBRARY)

def unpublish_book(user: str, slug: str, is_admin: bool, now: int) -> Book | None:
    """Move a library book back into its publisher's staging. Same contract
    as unpublish_deck (None -> 404, BookForbidden, BookConflict)."""
    src = user_books_dir(None) / slug
    manifest_path = src / "manifest.yaml"
    if not manifest_path.is_file():
        return None
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    publisher = manifest.get("published_by")
    if not is_admin and publisher != user:
        raise BookForbidden(slug)
    target = publisher if publisher and publisher != FORMER_MEMBER else user
    dest = user_books_dir(target) / slug
    if dest.exists():
        raise BookConflict(slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    update_manifest(dest, published_by=None, published_at=None)
    return _load_book(dest, owner=target, tier=STAGING)


def delete_book(user: str, slug: str) -> bool:
    """Delete `user`'s staging book outright. Keyed on the DIRECTORY, not the
    manifest, so a failed import (folder holding only source.pdf) can be
    cleaned up rather than stranding the slug. Library books must be
    unpublished first, which keeps deletion under the caller's own staging."""
    target = user_books_dir(user) / slug
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


# Words too generic to signal a book<->deck title match on their own.
_GENERIC_TITLE_WORDS = {
    "tarot", "guidebook", "guide", "the", "of", "to", "a", "an", "and",
    "deck", "cards", "card", "book", "companion", "edition", "lwb", "little",
    "white",
}


def _title_tokens(name: str) -> set[str]:
    import re as _re

    return {t for t in _re.split(r"[^a-z0-9]+", (name or "").lower())
            if t and t not in _GENERIC_TITLE_WORDS}


def suggest_books(deck, books: dict[str, Book]) -> list[str]:
    """Book slugs whose titles are 'nearby' a deck's — companion-curation
    suggestions for the deck's owner. A subset match (deck "Wyspell" vs book
    "Wyspell Gold Foil Tarot Guidebook") or strong token overlap qualifies;
    already-linked books are excluded. Best match first."""
    dt = _title_tokens(getattr(deck, "name", "") or "") | _title_tokens(deck.slug)
    if not dt:
        return []
    linked = set(getattr(deck, "books", []) or [])
    scored: list[tuple[float, str]] = []
    for slug, book in books.items():
        if slug in linked:
            continue
        bt = _title_tokens(book.name) | _title_tokens(slug)
        inter = bt & dt
        if not bt or not inter:
            continue
        jaccard = len(inter) / len(bt | dt)
        subset = bt <= dt or dt <= bt
        if subset or jaccard >= 0.5:
            scored.append((jaccard + (1.0 if subset else 0.0), slug))
    return [slug for _, slug in sorted(scored, reverse=True)]


# Major-arcana words used to spot contents/index pages masquerading as a card
# passage (a real passage rarely name-drops many OTHER majors in a few lines).
_MAJOR_WORDS = ("magician", "priestess", "empress", "emperor", "hierophant",
                "lovers", "chariot", "strength", "hermit", "justice", "hanged",
                "temperance", "devil", "tower", "judgement", "judgment")


def _index_like(text: str) -> bool:
    low = text.lower()
    return sum(w in low for w in _MAJOR_WORDS) >= 5


def passages_for(book: Book, index: int) -> list[dict]:
    """The per-card passage entries for one canonical index (may be []).
    Contents/toc-shaped passages are dropped when real ones exist, else
    ranked last."""
    try:
        cards = json.loads((book.path / "cards.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []
    entries = cards.get(str(index), [])
    real = [e for e in entries if not _index_like(e.get("text", ""))]
    # anchored sections first (PDF outline, then printed contents), then by
    # substance — stray in-prose name matches sink to the end (and out of
    # capped prompt joins)
    rank = {"toc": 0, "contents": 1}
    return sorted(real or entries,
                  key=lambda e: (rank.get(e.get("source"), 2),
                                 0 if e.get("primary") else 1,
                                 -len(e.get("text", ""))))


def passages_for_reading(user: str, slugs: list[str], indices: list[int],
                         cap: int = 600) -> dict[int, dict[str, str]]:
    """{card index: {book name: passage text}} for the drawn cards, from the
    visible books among `slugs` (invisible/unknown slugs are silently
    dropped — a shared reading may reference a book the viewer can't see).
    Upright+reversed passages are joined; each book's text is truncated to
    `cap` chars per card so prompt inflation stays bounded."""
    visible = discover_books(user)
    picked = [visible[s] for s in slugs if s in visible]
    out: dict[int, dict[str, str]] = {}
    for index in indices:
        per_book: dict[str, str] = {}
        for book in picked:
            parts = [e["text"] for e in passages_for(book, index) if e.get("text")]
            if parts:
                text = " ".join(" ".join(parts).split())
                per_book[book.name] = text[:cap].rsplit(" ", 1)[0] if len(text) > cap else text
        if per_book:
            out[index] = per_book
    return out
