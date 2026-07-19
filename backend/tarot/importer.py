"""Map arbitrary card-image filenames onto the canonical 0-77 index.

Recognized styles (mixable within one deck):
- numeric: 00.jpg … 77.jpg (canonical index, authoritative)
- named:   00-Major-Fool.jpg, 23-Minor-Discs-02.jpg, 78-Back.jpg — mapped by
  NAME, not number, so decks with Marseilles trump order (Justice VIII) or
  nonstandard suit order land correctly
- commons: Wands01.jpg … Wands14.jpg, Coins07.jpg, RWS_Tarot_08_Strength.jpg
- back:    any file whose name contains 'back' or 'reverse'

Suit synonyms (batons/staves→wands, chalices→cups, discs/coins→pentacles) and
court synonyms (knave/princess→page, prince→knight) are folded in.
"""

import re

MAJOR_ALIASES = {
    "fool": 0, "magician": 1, "juggler": 1, "bateleur": 1,
    "priestess": 2, "highpriestess": 2, "papess": 2, "popess": 2,
    "empress": 3, "emperor": 4,
    "hierophant": 5, "pope": 5,
    "lovers": 6, "lover": 6,
    "chariot": 7,
    "strength": 8, "strenght": 8, "force": 8, "fortitude": 8,
    "hermit": 9, "hermite": 9,
    "wheeloffortune": 10, "fortune": 10, "wheel": 10,
    "justice": 11,
    "hangedman": 12, "hanged": 12,
    "death": 13,
    "temperance": 14,
    "devil": 15,
    "tower": 16,
    "star": 17,
    "moon": 18,
    "sun": 19,
    "judgement": 20, "judgment": 20, "aeon": 20,
    "world": 21, "universe": 21,
}

SUIT_ALIASES = {
    "wands": 0, "wand": 0, "batons": 0, "baton": 0, "staves": 0, "staffs": 0, "rods": 0,
    "cups": 1, "cup": 1, "chalices": 1, "goblets": 1,
    "swords": 2, "sword": 2, "blades": 2, "epees": 2,
    "pentacles": 3, "pentacle": 3, "pents": 3, "discs": 3, "disks": 3, "disc": 3,
    "coins": 3, "coin": 3, "deniers": 3,
}

RANK_ALIASES = {
    "ace": 0,
    "page": 10, "knave": 10, "jack": 10, "princess": 10, "valet": 10,
    "knight": 11, "prince": 11, "cavalier": 11,
    "queen": 12, "reine": 12,
    "king": 13, "roi": 13,
}

NOISE_TOKENS = {"major", "minor", "tarot", "trump", "arcana", "card", "rws", "the", "of", "la", "le", "l"}


def _tokens(stem: str) -> list[str]:
    # split camelCase and letter/digit boundaries, then non-alphanumerics
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", s)
    return [t.lower() for t in re.split(r"[^A-Za-z0-9]+", s) if t]


def classify(stem: str) -> int | str | None:
    """Canonical index, 'back', or None if unrecognized."""
    tokens = _tokens(stem)
    alpha = [t for t in tokens if t.isalpha() and t not in NOISE_TOKENS]
    digits = [t for t in tokens if t.isdigit()]

    if any(t in ("back", "reverse", "reverso") for t in alpha):
        return "back"
    if any(t in ("box", "cover", "title", "lid") for t in alpha):
        return "ignore"

    # minors: suit + (named rank | numeric rank)
    suit = next((SUIT_ALIASES[t] for t in alpha if t in SUIT_ALIASES), None)
    if suit is not None:
        rank = next((RANK_ALIASES[t] for t in alpha if t in RANK_ALIASES), None)
        if rank is None and digits:
            n = int(digits[-1])
            if 1 <= n <= 14:
                rank = n - 1  # 01=ace … 10=ten, 11-14=courts (commons style)
        if rank is not None:
            return 22 + suit * 14 + rank

    # majors by name (joined tokens catch 'hanged man', 'wheel of fortune')
    joined = "".join(alpha)
    if joined in MAJOR_ALIASES:
        return MAJOR_ALIASES[joined]
    for t in alpha:
        if t in MAJOR_ALIASES:
            return MAJOR_ALIASES[t]

    # pure canonical number
    if not alpha and digits:
        n = int(digits[0])
        if 0 <= n <= 77:
            return n
    return None


def map_filenames(stems: list[str]) -> tuple[dict[int, str], str | None, list[str]]:
    """Returns (index->stem, back stem or None, unrecognized/conflicting stems)."""
    mapping: dict[int, str] = {}
    back: str | None = None
    problems: list[str] = []
    numeric: dict[str, int] = {}
    for stem in stems:
        tokens = _tokens(stem)
        alpha = [t for t in tokens if t.isalpha() and t not in NOISE_TOKENS]
        digits = [t for t in tokens if t.isdigit()]
        if not alpha and len(digits) >= 1:
            numeric[stem] = int(digits[0])
        kind = classify(stem)
        if kind == "back":
            back = back or stem
        elif kind == "ignore":
            continue
        elif isinstance(kind, int):
            if kind in mapping:
                problems.append(f"{stem}: maps to card {kind}, already taken by {mapping[kind]}")
            else:
                mapping[kind] = stem
        else:
            problems.append(f"{stem}: unrecognized")

    # 1-based pure-numeric decks (Card01…Card78): re-base so 1 -> The Fool
    if 0 not in mapping and len(numeric) >= 22 and min(numeric.values()) == 1 and max(numeric.values()) <= 79:
        mapping = {n - 1: stem for stem, n in numeric.items() if 0 <= n - 1 <= 77}
        problems = [f"{stem}: number {n} out of range" for stem, n in numeric.items() if n - 1 > 77]
    return mapping, back, problems
