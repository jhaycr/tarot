"""Reassign every owner surface from one user to another (auth Step 7).

Built to retire `local` — the shared anonymous identity of the header era —
but generalized: any user's data can be handed to another. DB ownership
moves in one transaction; staging folders and library attributions follow
best-effort (a crash between the two leaves a re-runnable state, never a
broken one — the operation is idempotent).

Deliberately untouched: reading_shares grantees (a share granted TO someone
stays theirs) and the users row itself (the source is deactivated, not
deleted — historical FK targets remain).
"""

import shutil

from tarot import db, sessions, users
from tarot.books import user_books_dir
from tarot.decks import update_manifest, user_decks_dir


def _move_staging(src_dir, dst_dir, moved: list[str], collisions: list[str], src: str) -> None:
    if not src_dir.is_dir():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for entry in sorted(src_dir.iterdir()):
        target = dst_dir / entry.name
        if target.exists():
            target = dst_dir / f"{entry.name}-from-{src}"
            collisions.append(entry.name)
            if target.exists():  # re-run after a previous partial move
                continue
        shutil.move(str(entry), str(target))
        moved.append(target.name)


def reassign_user_data(src: str, dst: str) -> dict:
    """Move readings, settings, spend history, staging decks/books and
    library attributions from `src` to `dst`; deactivate `src`."""
    report: dict = {"from": src, "to": dst}

    with db.connect() as con:
        report["readings"] = con.execute(
            "UPDATE readings SET owner = ? WHERE owner = ?", (dst, src)).rowcount
        # Settings: the destination's own choices win on conflict.
        con.execute(
            "INSERT OR IGNORE INTO user_settings (owner, key, value)"
            " SELECT ?, key, value FROM user_settings WHERE owner = ?", (dst, src))
        report["settings"] = con.execute(
            "DELETE FROM user_settings WHERE owner = ?", (src,)).rowcount
        # Spend history follows the person (design §4.6). Charges can collide
        # on (owner, day, fingerprint) if both users were charged for the
        # same draw — the duplicate row is then simply dropped.
        con.execute(
            "UPDATE OR IGNORE reading_charges SET owner = ? WHERE owner = ?", (dst, src))
        con.execute("DELETE FROM reading_charges WHERE owner = ?", (src,))
        report["usage_rows"] = con.execute(
            "UPDATE ai_usage SET owner = ? WHERE owner = ?", (dst, src)).rowcount

    moved: list[str] = []
    collisions: list[str] = []
    _move_staging(user_decks_dir(src), user_decks_dir(dst), moved, collisions, src)
    _move_staging(user_books_dir(src), user_books_dir(dst), moved, collisions, src)
    report["staging_moved"] = moved
    report["staging_collisions"] = collisions

    restamped: list[str] = []
    for library in (user_decks_dir(None), user_books_dir(None)):
        if not library.is_dir():
            continue
        for entry in sorted(library.iterdir()):
            manifest = entry / "manifest.yaml"
            if not manifest.is_file():
                continue
            import yaml

            data = yaml.safe_load(manifest.read_text()) or {}
            if data.get("published_by") == src:
                update_manifest(entry, published_by=dst)
                restamped.append(entry.name)
    report["library_restamped"] = restamped

    sessions.destroy_all(src)
    users.update(src, active=False)
    report["deactivated"] = True
    return report


def delete_user(username: str) -> dict:
    """Erase a user: their readings (interpretations and shares cascade),
    shares they had received, settings, sessions, draft folders — then the
    registry row itself. Library publications survive under the existing
    "former member" tombstone; the usage ledger is retained (instance
    accounting, names are just strings there).

    Route-level guards decide WHO may be deleted; this only does the work.
    """
    from tarot import dedupe
    from tarot.decks import FORMER_MEMBER

    report: dict = {"user": username}
    with db.connect() as con:
        report["readings"] = con.execute(
            "DELETE FROM readings WHERE owner = ?", (username,)).rowcount
        report["shares_received"] = con.execute(
            "DELETE FROM reading_shares WHERE grantee = ?", (username,)).rowcount
        report["settings"] = con.execute(
            "DELETE FROM user_settings WHERE owner = ?", (username,)).rowcount
        con.execute("DELETE FROM reading_charges WHERE owner = ?", (username,))
        con.execute("DELETE FROM sessions WHERE username = ?", (username,))

    removed: list[str] = []
    user_root = user_decks_dir(username).parent  # /data/users/<username>
    if user_root.is_dir():
        removed = sorted(p.name for d in ("decks", "books")
                         if (user_root / d).is_dir() for p in (user_root / d).iterdir())
        shutil.rmtree(user_root)
        dedupe.prune_orphans()
    report["drafts_removed"] = removed

    tombstoned: list[str] = []
    import yaml

    for library in (user_decks_dir(None), user_books_dir(None)):
        if not library.is_dir():
            continue
        for entry in sorted(library.iterdir()):
            manifest = entry / "manifest.yaml"
            if not manifest.is_file():
                continue
            data = yaml.safe_load(manifest.read_text()) or {}
            if data.get("published_by") == username:
                update_manifest(entry, published_by=FORMER_MEMBER)
                tombstoned.append(entry.name)
    report["library_tombstoned"] = tombstoned

    with db.connect() as con:
        con.execute("DELETE FROM users WHERE username = ?", (username,))
    report["deleted"] = True
    return report
