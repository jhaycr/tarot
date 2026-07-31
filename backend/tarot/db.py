"""Reading journal in SQLite (one file in the data dir)."""

import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager

from tarot.decks import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    question TEXT,
    deck TEXT NOT NULL,
    spread TEXT NOT NULL,
    cards TEXT NOT NULL,
    notes TEXT DEFAULT '',
    shared INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_readings_owner ON readings(owner, created_at DESC);
CREATE TABLE IF NOT EXISTS user_prompts (
    owner TEXT PRIMARY KEY,
    system_prompt TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


SCHEMA_VERSION_KEY = "schema_version"

# (version, migrate_fn). Applied in order, once each, newest last. A migration
# gets a connection in autocommit mode inside an explicit transaction; it must
# use con.execute directly rather than the module's public helpers, which would
# open a second connection and recurse.
def _m1_user_registry(con: sqlite3.Connection) -> None:
    """Create the user registry and backfill it from the three places that
    answered 'who is a user' before it existed.

    The three sources genuinely differ, so they must be unioned rather than
    trusted individually: a reading-only user has no directory, and a directory
    outlives the decks that created it.
    """
    from tarot.auth import ADMIN_USERS, FALLBACK_USER
    from tarot.decks import all_users

    con.execute(
        """
        CREATE TABLE users (
            username     TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            kind         TEXT NOT NULL DEFAULT 'person'
                           CHECK (kind IN ('person','system')),
            active       INTEGER NOT NULL DEFAULT 1,
            is_admin     INTEGER NOT NULL DEFAULT 0,
            first_seen   INTEGER NOT NULL,
            last_seen    INTEGER NOT NULL
        )
        """
    )

    now = int(time.time())
    names: set[str] = set()
    names.update(r[0] for r in con.execute("SELECT DISTINCT owner FROM readings"))
    names.update(r[0] for r in con.execute("SELECT owner FROM user_prompts"))
    names.update(all_users())

    # Earliest reading is a better first_seen than "now" for anyone who has one.
    earliest = {
        r[0]: r[1]
        for r in con.execute("SELECT owner, MIN(created_at) FROM readings GROUP BY owner")
    }

    for name in sorted(n for n in names if n):
        kind = "system" if name == FALLBACK_USER else "person"
        con.execute(
            "INSERT INTO users (username, display_name, kind, active, is_admin,"
            " first_seen, last_seen) VALUES (?,?,?,1,?,?,?)",
            (name, name, kind, int(name in ADMIN_USERS), earliest.get(name, now), now),
        )


def _m2_reading_visibility(con: sqlite3.Connection) -> None:
    """Replace the binary `shared` flag with three-state visibility.

    The mapping is unambiguous because there was no way to be 'specific' before:
    shared=1 meant everyone on the instance, shared=0 meant nobody.
    """
    con.execute(
        "ALTER TABLE readings ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'"
        " CHECK (visibility IN ('private','specific','everyone'))"
    )
    con.execute(
        "UPDATE readings SET visibility = CASE WHEN shared = 1"
        " THEN 'everyone' ELSE 'private' END"
    )
    con.execute("ALTER TABLE readings DROP COLUMN shared")
    con.execute(
        """
        CREATE TABLE reading_shares (
            reading_id INTEGER NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
            grantee    TEXT    NOT NULL REFERENCES users(username),
            granted_at INTEGER NOT NULL,
            PRIMARY KEY (reading_id, grantee)
        )
        """
    )
    # Serves "readings shared with me", which would otherwise scan.
    con.execute(
        "CREATE INDEX idx_reading_shares_grantee ON reading_shares(grantee)"
    )


def _m3_publish_decks(con: sqlite3.Connection) -> None:
    """Publish legacy shared decks (and all of `local`'s decks) into the shared
    library. Filesystem-only — no schema change; gated by schema_version so it
    runs exactly once. See decks.migrate_publish_decks for the policy.
    """
    from tarot import decks

    published, skipped = decks.migrate_publish_decks(int(time.time()))
    print(f"[migration 3] published {len(published)} deck(s) to the library: {published}")
    if skipped:
        print(f"[migration 3] skipped {len(skipped)}: {skipped}")


def _m4_guided_interpretations(con: sqlite3.Connection) -> None:
    """Persist guided-reading interpretation text.

    Reading-level singletons (which context mode, overall status) live as columns
    on `readings` so the journal list can badge a reading without a join. The
    per-card and whole-spread text lives in a child table, CASCADE-deleted with
    the parent, matching the reading_shares precedent. A focused row exists iff
    that card position has been interpreted, so completion state is intrinsic and
    the flow is resumable.
    """
    con.execute(
        "ALTER TABLE readings ADD COLUMN interpretation_mode TEXT "
        "CHECK (interpretation_mode IS NULL OR "
        "interpretation_mode IN ('isolated','cumulative','single'))"
    )
    con.execute(
        "ALTER TABLE readings ADD COLUMN interpretation_status TEXT "
        "CHECK (interpretation_status IS NULL OR "
        "interpretation_status IN ('in_progress','complete'))"
    )
    con.execute(
        """
        CREATE TABLE reading_interpretations (
            reading_id INTEGER NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
            position   INTEGER NOT NULL,   -- 0-based ordinal into readings.cards;
                                           -- -1 = whole-spread (comprehensive/single)
            kind       TEXT    NOT NULL CHECK (kind IN ('focused','comprehensive')),
            text       TEXT    NOT NULL,
            persona    TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (reading_id, position),
            CHECK ((kind = 'focused'       AND position >= 0) OR
                   (kind = 'comprehensive' AND position = -1))
        )
        """
    )


def _m5_tts(con: sqlite3.Connection) -> None:
    """TTS audio cache index (LRU by last_used_at; files live in
    /data/tts-cache) + a per-user voice block for the custom persona."""
    con.execute(
        """
        CREATE TABLE tts_cache (
            hash         TEXT PRIMARY KEY,
            size_bytes   INTEGER NOT NULL,
            created_at   INTEGER NOT NULL,
            last_used_at INTEGER NOT NULL
        )
        """
    )
    con.execute("ALTER TABLE user_prompts ADD COLUMN voice TEXT")


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _m1_user_registry),
    (2, _m2_reading_visibility),
    (3, _m3_publish_decks),
    (4, _m4_guided_interpretations),
    (5, _m5_tts),
]


def _schema_version(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT value FROM app_settings WHERE key = ?", (SCHEMA_VERSION_KEY,)
    ).fetchone()
    if row is None:
        return -1  # unmarked: never migrated, not even baselined
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def _set_schema_version(con: sqlite3.Connection, version: int) -> None:
    con.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION_KEY, str(version)),
    )


def _backup(con: sqlite3.Connection, version: int) -> None:
    """Snapshot the DB before a migration alters it.

    Uses the sqlite backup API rather than copying the file: in WAL mode recent
    commits can still be sitting in journal.db-wal, so a plain copy can lose
    them.
    """
    dest = data_dir() / f"journal.db.bak-v{version}"
    bak = sqlite3.connect(dest)
    try:
        con.backup(bak)
    finally:
        bak.close()


def _migrate(con: sqlite3.Connection) -> None:
    current = _schema_version(con)
    pending = [(v, fn) for v, fn in MIGRATIONS if v > max(current, 0)]
    if not pending:
        if current < 0:
            _set_schema_version(con, 0)  # baseline an existing/new DB
            con.commit()
        return

    _backup(con, max(current, 0))

    # Autocommit so BEGIN/COMMIT are ours: SQLite DDL *is* transactional, but
    # Python's legacy isolation handling won't wrap it for us.
    prior = con.isolation_level
    con.isolation_level = None
    try:
        for version, fn in pending:
            con.execute("BEGIN")
            try:
                fn(con)
                _set_schema_version(con, version)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
    finally:
        con.isolation_level = prior


@contextmanager
def connect():
    data_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(data_dir() / "journal.db")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    _migrate(con)
    try:
        yield con
        con.commit()
    finally:
        con.close()


PRIVATE, SPECIFIC, EVERYONE = "private", "specific", "everyone"
VISIBILITIES = (PRIVATE, SPECIFIC, EVERYONE)

# Visible if you own it, it's public, or someone granted it to you.
_VISIBLE = (
    "(owner = :me OR visibility = 'everyone'"
    " OR id IN (SELECT reading_id FROM reading_shares WHERE grantee = :me))"
)


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["cards"] = json.loads(d["cards"])
    return d


def _attach_shares(con: sqlite3.Connection, rows: list[dict]) -> list[dict]:
    """Fill in `shared_with` for the whole batch in one query."""
    ids = [r["id"] for r in rows if r["visibility"] == SPECIFIC]
    grants: dict[int, list[str]] = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for rid, grantee in con.execute(
            f"SELECT reading_id, grantee FROM reading_shares"
            f" WHERE reading_id IN ({marks}) ORDER BY grantee",
            ids,
        ):
            grants.setdefault(rid, []).append(grantee)
    for r in rows:
        r["shared_with"] = grants.get(r["id"], [])
    return rows


# Guided-reading interpretation. The whole-spread (comprehensive/single) row uses
# this sentinel position so a plain composite PK enforces one-per-card and exactly
# one whole-spread row (SQLite lets NULL duplicate in a PK, hence -1 not NULL).
POSITION_WHOLE = -1


def _attach_interpretations(con: sqlite3.Connection, rows: list[dict], full: bool = False) -> list[dict]:
    """Fold the reading-level interpretation columns into a nested object, and —
    when full — the per-card/whole-spread text rows. Keeps the raw columns from
    leaking as top-level keys."""
    for r in rows:
        r["interpretation"] = {
            "mode": r.pop("interpretation_mode", None),
            "status": r.pop("interpretation_status", None) or "none",
        }
    if not full:
        return rows
    ids = [r["id"] for r in rows]
    if ids:
        marks = ",".join("?" * len(ids))
        by_reading: dict[int, list] = {}
        for ir in con.execute(
            f"SELECT reading_id, position, kind, text FROM reading_interpretations"
            f" WHERE reading_id IN ({marks}) ORDER BY position",
            ids,
        ):
            by_reading.setdefault(ir["reading_id"], []).append(ir)
        for r in rows:
            focused, comprehensive, done = {}, None, []
            for ir in by_reading.get(r["id"], []):
                if ir["kind"] == "comprehensive":
                    comprehensive = ir["text"]
                else:
                    focused[str(ir["position"])] = ir["text"]
                    done.append(ir["position"])
            r["interpretation"].update(
                focused=focused, comprehensive=comprehensive, done_positions=done
            )
    return rows


def _reading_dict(con: sqlite3.Connection, row, full: bool) -> dict:
    """Standard single-reading dict: cards parsed, shares + interpretation attached."""
    d = _attach_shares(con, [_row_to_dict(row)])[0]
    return _attach_interpretations(con, [d], full=full)[0]


def save_reading(owner: str, question: str | None, deck: str, spread: str, cards: list, notes: str = "") -> dict:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO readings (owner, created_at, question, deck, spread, cards, notes) VALUES (?,?,?,?,?,?,?)",
            (owner, int(time.time()), question, deck, spread, json.dumps(cards), notes),
        )
        row = con.execute("SELECT * FROM readings WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _reading_dict(con, row, full=True)


def list_readings(owner: str, include_shared: bool = True) -> list[dict]:
    with connect() as con:
        if include_shared:
            rows = con.execute(
                f"SELECT * FROM readings WHERE {_VISIBLE} ORDER BY created_at DESC",
                {"me": owner},
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM readings WHERE owner = ? ORDER BY created_at DESC", (owner,)
            ).fetchall()
        dicts = _attach_shares(con, [_row_to_dict(r) for r in rows])
        return _attach_interpretations(con, dicts, full=False)


def get_reading(reading_id: int, owner: str) -> dict | None:
    with connect() as con:
        row = con.execute(
            f"SELECT * FROM readings WHERE id = :id AND {_VISIBLE}",
            {"id": reading_id, "me": owner},
        ).fetchone()
        return _reading_dict(con, row, full=True) if row else None


def update_reading(reading_id: int, owner: str, notes: str | None = None) -> dict | None:
    with connect() as con:
        if notes is not None:
            con.execute(
                "UPDATE readings SET notes = ? WHERE id = ? AND owner = ?",
                (notes, reading_id, owner),
            )
        row = con.execute(
            "SELECT * FROM readings WHERE id = ? AND owner = ?", (reading_id, owner)
        ).fetchone()
        return _reading_dict(con, row, full=True) if row else None


def create_guided_reading(
    owner: str, question: str | None, deck: str, spread: str,
    cards: list, mode: str, notes: str = "",
) -> dict:
    """Create the in-progress reading up front (cards known, no text yet)."""
    with connect() as con:
        cur = con.execute(
            "INSERT INTO readings (owner, created_at, question, deck, spread, cards,"
            " notes, interpretation_mode, interpretation_status)"
            " VALUES (?,?,?,?,?,?,?,?, 'in_progress')",
            (owner, int(time.time()), question, deck, spread, json.dumps(cards), notes, mode),
        )
        row = con.execute("SELECT * FROM readings WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _reading_dict(con, row, full=True)


def _owns(con: sqlite3.Connection, reading_id: int, owner: str) -> bool:
    return con.execute(
        "SELECT 1 FROM readings WHERE id = ? AND owner = ?", (reading_id, owner)
    ).fetchone() is not None


def set_focused_interpretation(
    reading_id: int, owner: str, position: int, text: str, persona: str | None = None,
) -> dict | None:
    """Upsert one card's focused reading. Owner-gated; idempotent (re-stream overwrites)."""
    with connect() as con:
        if not _owns(con, reading_id, owner):
            return None
        now = int(time.time())
        con.execute(
            "INSERT INTO reading_interpretations"
            " (reading_id, position, kind, text, persona, created_at, updated_at)"
            " VALUES (?,?, 'focused', ?,?,?,?)"
            " ON CONFLICT(reading_id, position) DO UPDATE SET"
            " text = excluded.text, persona = excluded.persona, updated_at = excluded.updated_at",
            (reading_id, position, text, persona, now, now),
        )
        # A single-card reading has no comprehensive step (the one focused
        # reading IS the whole picture), so it completes here.
        cards = con.execute(
            "SELECT cards FROM readings WHERE id = ?", (reading_id,)
        ).fetchone()["cards"]
        if len(json.loads(cards)) == 1:
            con.execute(
                "UPDATE readings SET interpretation_status = 'complete' WHERE id = ?",
                (reading_id,),
            )
        row = con.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
        return _reading_dict(con, row, full=True)


def set_comprehensive_interpretation(
    reading_id: int, owner: str, text: str, persona: str | None = None,
) -> dict | None:
    """Upsert the whole-spread interpretation and mark the reading complete."""
    with connect() as con:
        if not _owns(con, reading_id, owner):
            return None
        now = int(time.time())
        con.execute(
            "INSERT INTO reading_interpretations"
            " (reading_id, position, kind, text, persona, created_at, updated_at)"
            " VALUES (?,?, 'comprehensive', ?,?,?,?)"
            " ON CONFLICT(reading_id, position) DO UPDATE SET"
            " text = excluded.text, persona = excluded.persona, updated_at = excluded.updated_at",
            (reading_id, POSITION_WHOLE, text, persona, now, now),
        )
        con.execute(
            "UPDATE readings SET interpretation_status = 'complete' WHERE id = ?", (reading_id,)
        )
        row = con.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
        return _reading_dict(con, row, full=True)


def get_focused_interpretations(reading_id: int, owner: str) -> dict[int, str]:
    """position -> focused text, for feeding the comprehensive prompt. Owner-gated."""
    with connect() as con:
        if not _owns(con, reading_id, owner):
            return {}
        return {
            ir["position"]: ir["text"]
            for ir in con.execute(
                "SELECT position, text FROM reading_interpretations"
                " WHERE reading_id = ? AND kind = 'focused' ORDER BY position",
                (reading_id,),
            )
        }


def set_sharing(reading_id: int, owner: str, visibility: str, grantees: list[str]) -> dict | None:
    """Set visibility and grantee list together. Owner-gated.

    Anything but 'specific' clears the grantee list, so state can't drift into
    'private, but with dangling grants'.
    """
    with connect() as con:
        owned = con.execute(
            "SELECT 1 FROM readings WHERE id = ? AND owner = ?", (reading_id, owner)
        ).fetchone()
        if owned is None:
            return None
        con.execute(
            "UPDATE readings SET visibility = ? WHERE id = ? AND owner = ?",
            (visibility, reading_id, owner),
        )
        con.execute("DELETE FROM reading_shares WHERE reading_id = ?", (reading_id,))
        if visibility == SPECIFIC and grantees:
            now = int(time.time())
            con.executemany(
                "INSERT INTO reading_shares (reading_id, grantee, granted_at) VALUES (?,?,?)",
                [(reading_id, g, now) for g in grantees],
            )
        row = con.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
        return _attach_shares(con, [_row_to_dict(row)])[0]


def shares_granted(owner: str) -> list[dict]:
    """Readings this user has shared, each with its grantee list — the account
    page's revoke list. `everyone`-visible readings are included too, with an
    empty grantee list, so they can be seen and made private again.
    """
    with connect() as con:
        readings = con.execute(
            "SELECT id, question, deck, spread, created_at, visibility FROM readings"
            " WHERE owner = ? AND visibility != 'private' ORDER BY created_at DESC",
            (owner,),
        ).fetchall()
        rows = [dict(r) for r in readings]
        _attach_shares(con, rows)  # fills shared_with per row
        return rows


def shares_received(user: str) -> list[dict]:
    """Readings other people have shared specifically with this user."""
    with connect() as con:
        rows = con.execute(
            "SELECT r.id, r.owner, r.question, r.deck, r.spread, r.created_at, s.granted_at"
            " FROM reading_shares s JOIN readings r ON r.id = s.reading_id"
            " WHERE s.grantee = ? ORDER BY s.granted_at DESC",
            (user,),
        ).fetchall()
        return [dict(r) for r in rows]


def owned_reading_count(owner: str) -> int:
    with connect() as con:
        return con.execute(
            "SELECT count(*) FROM readings WHERE owner = ?", (owner,)
        ).fetchone()[0]


def get_user_prompt(owner: str) -> str:
    with connect() as con:
        row = con.execute(
            "SELECT system_prompt FROM user_prompts WHERE owner = ?", (owner,)
        ).fetchone()
        return row["system_prompt"] if row else ""


def set_user_prompt(owner: str, system_prompt: str) -> None:
    with connect() as con:
        if system_prompt.strip():
            con.execute(
                "INSERT INTO user_prompts (owner, system_prompt) VALUES (?, ?) "
                "ON CONFLICT(owner) DO UPDATE SET system_prompt = excluded.system_prompt",
                (owner, system_prompt),
            )
        else:
            con.execute("DELETE FROM user_prompts WHERE owner = ?", (owner,))


def get_user_voice(owner: str) -> dict | None:
    """The custom persona's voice block, or None. Lives on the user_prompts
    row, so it exists only while a custom prompt does."""
    with connect() as con:
        row = con.execute(
            "SELECT voice FROM user_prompts WHERE owner = ?", (owner,)
        ).fetchone()
        if not row or not row["voice"]:
            return None
        try:
            parsed = json.loads(row["voice"])
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None


def set_user_voice(owner: str, voice: dict | None) -> None:
    """Attach a voice block to the user's custom prompt row (no-op without one)."""
    with connect() as con:
        con.execute(
            "UPDATE user_prompts SET voice = ? WHERE owner = ?",
            (json.dumps(voice) if voice else None, owner),
        )


def get_interpretation(reading_id: int, position: int) -> dict | None:
    """One interpretation row (text + persona). NOT visibility-gated — call
    after get_reading() has already established the viewer may see it."""
    with connect() as con:
        row = con.execute(
            "SELECT position, kind, text, persona FROM reading_interpretations"
            " WHERE reading_id = ? AND position = ?",
            (reading_id, position),
        ).fetchone()
        return dict(row) if row else None


# --- TTS cache index (LRU; files live in /data/tts-cache) -------------------

def tts_cache_all() -> list[dict]:
    """All entries, least-recently-played first (eviction order)."""
    with connect() as con:
        return [
            dict(r)
            for r in con.execute(
                "SELECT hash, size_bytes, last_used_at FROM tts_cache ORDER BY last_used_at"
            )
        ]


def tts_cache_upsert(hash_: str, size_bytes: int) -> None:
    now = int(time.time())
    with connect() as con:
        con.execute(
            "INSERT INTO tts_cache (hash, size_bytes, created_at, last_used_at)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(hash) DO UPDATE SET"
            " size_bytes = excluded.size_bytes, last_used_at = excluded.last_used_at",
            (hash_, size_bytes, now, now),
        )


def tts_cache_touch(hash_: str) -> None:
    """Bump last_used_at, throttled to daily so replays don't churn writes."""
    now = int(time.time())
    with connect() as con:
        con.execute(
            "UPDATE tts_cache SET last_used_at = ? WHERE hash = ? AND last_used_at < ?",
            (now, hash_, now - 86400),
        )


def tts_cache_delete(hash_: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM tts_cache WHERE hash = ?", (hash_,))


def get_setting(key: str) -> str:
    with connect() as con:
        row = con.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else ""


def set_setting(key: str, value: str) -> None:
    with connect() as con:
        if value:
            con.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        else:
            con.execute("DELETE FROM app_settings WHERE key = ?", (key,))


def delete_reading(reading_id: int, owner: str) -> bool:
    with connect() as con:
        cur = con.execute("DELETE FROM readings WHERE id = ? AND owner = ?", (reading_id, owner))
        return cur.rowcount > 0
