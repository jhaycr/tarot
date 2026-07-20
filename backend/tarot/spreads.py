"""Spread definitions. Positions carry layout hints (col/row) for the frontend grid.

The three below are hand-tuned (the Celtic Cross crossing card especially).
Additional spreads are imported from the TarotSchema codex — regenerate with
`python tools/import_tarotschema.py`; their prose is CC-BY-4.0 by Tarotsmith,
so imported spreads carry an `attribution` block that the UI displays.
"""

import json
from pathlib import Path

BUILTIN_SPREADS = [
    {
        "slug": "single",
        "name": "Single Card",
        "description": "One card for a quick daily draw or a yes/no pulse.",
        "positions": [
            {"name": "The Card", "meaning": "The heart of the matter", "col": 1, "row": 1},
        ],
    },
    {
        "slug": "three-card",
        "name": "Three Card",
        "description": "Past, present, future — or situation, action, outcome.",
        "positions": [
            {"name": "Past", "meaning": "What brought you here", "col": 1, "row": 1},
            {"name": "Present", "meaning": "Where you stand now", "col": 2, "row": 1},
            {"name": "Future", "meaning": "Where this is heading", "col": 3, "row": 1},
        ],
    },
    {
        "slug": "celtic-cross",
        "name": "Celtic Cross",
        "description": "The classic ten-card deep dive into a question.",
        "positions": [
            {"name": "Present", "meaning": "The heart of the situation", "col": 2, "row": 2},
            {"name": "Challenge", "meaning": "What crosses you", "col": 2, "row": 2, "cross": True},
            {"name": "Foundation", "meaning": "The root of the matter", "col": 2, "row": 3},
            {"name": "Past", "meaning": "What is passing away", "col": 1, "row": 2},
            {"name": "Crown", "meaning": "What crowns the question", "col": 2, "row": 1},
            {"name": "Future", "meaning": "What approaches", "col": 3, "row": 2},
            {"name": "Self", "meaning": "How you see yourself", "col": 4, "row": 4},
            {"name": "Environment", "meaning": "Outside influences", "col": 4, "row": 3},
            {"name": "Hopes & Fears", "meaning": "What you hope for and dread", "col": 4, "row": 2},
            {"name": "Outcome", "meaning": "Where it all resolves", "col": 4, "row": 1},
        ],
    },
]

def _load_imported() -> list[dict]:
    path = Path(__file__).parent / "data" / "spreads_tarotschema.json"
    if not path.is_file():
        return []
    doc = json.loads(path.read_text())
    attribution = doc.get("attribution")
    spreads = []
    for s in doc.get("spreads", []):
        if s["slug"] in {b["slug"] for b in BUILTIN_SPREADS}:
            continue  # never shadow a hand-tuned layout
        spreads.append({**s, "attribution": attribution})
    return spreads


IMPORTED_SPREADS = _load_imported()

# built-ins first (the everyday spreads), then imported ones by card count
SPREADS = BUILTIN_SPREADS + sorted(IMPORTED_SPREADS, key=lambda s: (len(s["positions"]), s["name"]))

SPREADS_BY_SLUG = {s["slug"]: s for s in SPREADS}
