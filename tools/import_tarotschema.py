"""Import spread definitions from the TarotSchema codex into Tarotarium's format.

Source: https://github.com/TarotSchema/codex (spreads-schema.json)
Licensing: schema structure is MIT; the spread/position prose is CC-BY-4.0 by
Tarotsmith (Jeremy Lampkin), so the generated file carries attribution and the
app displays it wherever imported spreads appear.

Run:  python tools/import_tarotschema.py [--out backend/tarot/data/spreads_tarotschema.json]

TarotSchema gives positions as plain strings, in two shapes:
    "The Past: Past events affecting the question."   -> name + meaning
    "significator"                                    -> name only
and carries no layout geometry, so table positions are auto-arranged here.
"""

import argparse
import json
import re
import urllib.request
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/TarotSchema/codex/main/spreads-schema.json"

# Spreads Tarotarium already ships with hand-tuned layouts (the Celtic Cross
# crossing card in particular); don't replace those with auto-arranged copies.
SKIP_IDS = {"spread_single", "spread_three", "spread_celticcross"}

MAX_PER_ROW = 5


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return re.sub(r"-spread$", "", s) or "spread"


# prose openers that carry no meaning in a position label
FILLER = re.compile(
    r"^(?:this (?:card|position)\s+(?:displays|indicates|shows|represents|deals with|is)\s+"
    r"|this is\s+|it (?:deals with|represents|shows|is)\s+|here (?:is|lies)\s+)",
    re.I,
)


DANGLING = re.compile(
    r"\s+(?:that|which|who|whom|whose|to|of|and|or|the|a|an|for|in|on|with|from|as|is|are)$",
    re.I,
)


def shorten(text: str, limit: int = 38) -> str:
    """Trim to a label-length phrase on a word boundary, without a dangling word."""
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0]
    text = text.rstrip(" ,;:")
    while True:
        trimmed = DANGLING.sub("", text)
        if trimmed == text:
            return text
        text = trimmed


def parse_position(raw: str) -> tuple[str, str]:
    """-> (name, meaning). Handles 'Label: prose', bare labels, and long prose."""
    text = raw.strip()
    if ":" in text:
        label, _, rest = text.partition(":")
        if len(label) <= 40:
            return label.strip(), rest.strip()
    if len(text) <= 40:
        return text[:1].upper() + text[1:], ""
    # long prose with no label: derive a label from the lead clause, keeping the
    # full sentence as the meaning
    lead = re.split(r"[,.;]", text, maxsplit=1)[0].strip()
    lead = FILLER.sub("", lead).strip() or lead
    lead = shorten(lead)
    return lead[:1].upper() + lead[1:], text


def auto_layout(count: int) -> list[tuple[int, int]]:
    """Arrange N positions into a tidy grid, reading order."""
    per_row = count if count <= MAX_PER_ROW else min(MAX_PER_ROW, (count + 1) // 2)
    return [(i % per_row + 1, i // per_row + 1) for i in range(count)]


def convert(doc: dict) -> dict:
    meta = doc.get("metadata", {})
    spreads = []
    for entry in doc.get("spreads", []):
        if entry.get("id") in SKIP_IDS:
            continue
        positions_raw = entry.get("card_positions") or []
        if not positions_raw:
            continue
        layout = auto_layout(len(positions_raw))
        positions = []
        for raw, (col, row) in zip(positions_raw, layout):
            name, meaning = parse_position(raw)
            positions.append({"name": name, "meaning": meaning, "col": col, "row": row})
        spreads.append({
            "slug": slugify(entry.get("spread_name", entry.get("id", ""))),
            "name": entry.get("spread_name", "").strip(),
            "description": (entry.get("description") or "").strip(),
            "difficulty": entry.get("difficulty"),
            "positions": positions,
            "imported": True,
        })
    return {
        "attribution": {
            "source": "TarotSchema codex",
            "author": meta.get("author", "Tarotsmith"),
            "url": meta.get("canonical", "https://github.com/TarotSchema/codex"),
            "license": "CC-BY-4.0 (spread text) / MIT (schema structure)",
            "schema_version": meta.get("schema_version"),
            "updated": meta.get("updated"),
        },
        "spreads": spreads,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=SOURCE_URL)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent.parent / "backend" / "tarot" / "data" / "spreads_tarotschema.json",
    )
    args = ap.parse_args()

    with urllib.request.urlopen(args.url) as resp:
        doc = json.load(resp)
    out = convert(doc)
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    counts = ", ".join(f"{s['name']} ({len(s['positions'])})" for s in out["spreads"][:4])
    print(f"{len(out['spreads'])} spreads -> {args.out}")
    print(f"e.g. {counts} …")


if __name__ == "__main__":
    main()
