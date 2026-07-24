"""User registry — the app's record of who exists.

Identity itself still comes from the proxy header (see auth.py); this is a
projection of it, never an authentication source. Rows appear on first sight, so
the registry is complete without anyone provisioning it: authentik's group
membership is already the gate on who can reach the app at all.

Before this existed, "who is a user" was answered three unconnected ways — the
request header, `readings.owner` strings, and directories under data/users/ —
and a username existed only as a side effect of having saved something.
"""

import time

from tarot import db
from tarot.auth import FALLBACK_USER, is_admin

# Refresh last_seen at most this often, so ordinary browsing doesn't write on
# every request.
TOUCH_INTERVAL = 300

KIND_PERSON = "person"
KIND_SYSTEM = "system"


def kind_for(username: str) -> str:
    """`local` is the shared header-absent LAN identity, not a person. It owns
    real data but can never be a meaningful share recipient."""
    return KIND_SYSTEM if username == FALLBACK_USER else KIND_PERSON


def _row(r) -> dict:
    d = dict(r)
    d["active"] = bool(d["active"])
    d["is_admin"] = bool(d["is_admin"])
    return d


def touch(username: str, display: str | None = None) -> None:
    """Record that `username` is here. Cheap on the common path: a primary-key
    read, and a write only when the row is new, stale, or renamed."""
    now = int(time.time())
    name = (display or username)[:64]
    with db.connect() as con:
        row = con.execute(
            "SELECT display_name, last_seen FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO users (username, display_name, kind, active, is_admin,"
                " first_seen, last_seen) VALUES (?,?,?,1,?,?,?)"
                " ON CONFLICT(username) DO NOTHING",
                (username, name, kind_for(username), int(is_admin(username)), now, now),
            )
            return
        if now - row["last_seen"] >= TOUCH_INTERVAL or row["display_name"] != name:
            con.execute(
                "UPDATE users SET last_seen = ?, display_name = ? WHERE username = ?",
                (now, name, username),
            )


def get(username: str) -> dict | None:
    with db.connect() as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return _row(row) if row else None


def list_people(include_inactive: bool = False) -> list[dict]:
    """People who can be picked as share recipients. Excludes system identities
    (`local`) and, by default, anyone an admin has deactivated."""
    sql = "SELECT * FROM users WHERE kind = ?"
    params: list = [KIND_PERSON]
    if not include_inactive:
        sql += " AND active = 1"
    sql += " ORDER BY display_name COLLATE NOCASE, username"
    with db.connect() as con:
        return [_row(r) for r in con.execute(sql, params)]


def list_all() -> list[dict]:
    with db.connect() as con:
        return [
            _row(r)
            for r in con.execute(
                "SELECT * FROM users ORDER BY kind, display_name COLLATE NOCASE, username"
            )
        ]


def is_grantable(username: str) -> bool:
    """Whether a reading may be shared with `username`."""
    u = get(username)
    return bool(u and u["active"] and u["kind"] == KIND_PERSON)


def update(username: str, display_name: str | None = None, active: bool | None = None) -> dict | None:
    """Admin curation: rename, or hide a stale/mistyped entry from pickers."""
    with db.connect() as con:
        if con.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is None:
            return None
        if display_name is not None:
            con.execute(
                "UPDATE users SET display_name = ? WHERE username = ?",
                (display_name[:64] or username, username),
            )
        if active is not None:
            con.execute(
                "UPDATE users SET active = ? WHERE username = ?", (int(active), username)
            )
        return _row(con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
