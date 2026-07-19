"""Content-addressed dedupe for deck images.

Identical card images (e.g. the same deck downloaded by several users) are
stored once under $TAROT_DATA_DIR/objects/<aa>/<sha256>.<ext>; deck card files
become hardlinks to the object. Decks stay independent folders — deleting one
never affects another, and objects whose last deck link is gone are pruned
opportunistically.

Only files on the data-dir filesystem participate (hardlinks can't cross
devices, so builtin decks baked into the image are skipped automatically).
"""

import hashlib
import os
from pathlib import Path

from tarot.decks import IMAGE_EXTS, data_dir, user_decks_dir


def objects_dir() -> Path:
    return data_dir() / "objects"


def _dedupe_file(f: Path) -> bool:
    """Replace f with a hardlink into the object store. True if bytes were shared."""
    digest = hashlib.sha256(f.read_bytes()).hexdigest()
    obj = objects_dir() / digest[:2] / f"{digest}{f.suffix.lower()}"
    try:
        if obj.exists():
            if f.samefile(obj):
                return False
            tmp = f.with_name(f.name + ".dedupe-tmp")
            os.link(obj, tmp)
            os.replace(tmp, f)
            return True
        obj.parent.mkdir(parents=True, exist_ok=True)
        os.link(f, obj)
        return False
    except OSError:
        # cross-device, or a filesystem without hardlinks — leave the file alone
        return False


def dedupe_deck(deck_dir: Path) -> int:
    """Dedupe all images in one deck folder. Returns count of files now shared."""
    shared = 0
    candidates = []
    cards = deck_dir / "cards"
    if cards.is_dir():
        candidates.extend(cards.iterdir())
    candidates.extend(p for p in deck_dir.iterdir() if p.is_file())
    for f in candidates:
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            if _dedupe_file(f):
                shared += 1
    return shared


def dedupe_all() -> int:
    """Dedupe every deck in the data dir (instance + all users); prune dead objects."""
    shared = 0
    roots = [user_decks_dir(None)]
    users_root = data_dir() / "users"
    if users_root.is_dir():
        roots.extend(u / "decks" for u in users_root.iterdir() if u.is_dir())
    for root in roots:
        if root.is_dir():
            for deck_dir in root.iterdir():
                if deck_dir.is_dir():
                    shared += dedupe_deck(deck_dir)
    prune_orphans()
    return shared


def prune_orphans() -> int:
    """Remove objects no deck links to anymore (st_nlink == 1)."""
    removed = 0
    root = objects_dir()
    if not root.is_dir():
        return 0
    for bucket in root.iterdir():
        if not bucket.is_dir():
            continue
        for obj in bucket.iterdir():
            if obj.is_file() and obj.stat().st_nlink == 1:
                obj.unlink()
                removed += 1
    return removed
