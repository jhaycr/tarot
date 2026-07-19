"""Reading journal in SQLite (one file in the data dir)."""

import json
import sqlite3
import time
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
"""


@contextmanager
def connect():
    data_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(data_dir() / "journal.db")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["cards"] = json.loads(d["cards"])
    d["shared"] = bool(d["shared"])
    return d


def save_reading(owner: str, question: str | None, deck: str, spread: str, cards: list, notes: str = "") -> dict:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO readings (owner, created_at, question, deck, spread, cards, notes) VALUES (?,?,?,?,?,?,?)",
            (owner, int(time.time()), question, deck, spread, json.dumps(cards), notes),
        )
        row = con.execute("SELECT * FROM readings WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_dict(row)


def list_readings(owner: str, include_shared: bool = True) -> list[dict]:
    with connect() as con:
        if include_shared:
            rows = con.execute(
                "SELECT * FROM readings WHERE owner = ? OR shared = 1 ORDER BY created_at DESC",
                (owner,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM readings WHERE owner = ? ORDER BY created_at DESC", (owner,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_reading(reading_id: int, owner: str) -> dict | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM readings WHERE id = ? AND (owner = ? OR shared = 1)",
            (reading_id, owner),
        ).fetchone()
        return _row_to_dict(row) if row else None


def update_reading(reading_id: int, owner: str, notes: str | None = None, shared: bool | None = None) -> dict | None:
    with connect() as con:
        if notes is not None:
            con.execute(
                "UPDATE readings SET notes = ? WHERE id = ? AND owner = ?",
                (notes, reading_id, owner),
            )
        if shared is not None:
            con.execute(
                "UPDATE readings SET shared = ? WHERE id = ? AND owner = ?",
                (int(shared), reading_id, owner),
            )
        row = con.execute(
            "SELECT * FROM readings WHERE id = ? AND owner = ?", (reading_id, owner)
        ).fetchone()
        return _row_to_dict(row) if row else None


def delete_reading(reading_id: int, owner: str) -> bool:
    with connect() as con:
        cur = con.execute("DELETE FROM readings WHERE id = ? AND owner = ?", (reading_id, owner))
        return cur.rowcount > 0
