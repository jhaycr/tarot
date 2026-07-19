"""Site adapters: turn a deck source into {canonical_index: image_url}.

Canonical index: 0-21 majors, then wands/cups/swords/pentacles, each
ace,2..10,page,knight,queen,king (see tarot.cards).
"""

import re
from urllib.parse import urlparse

import httpx

from tarot.cards import CARDS


def camel(name: str) -> str:
    """'Wheel of Fortune' -> 'WheelOfFortune' (elvitarot filename convention)."""
    return name.title().replace(" ", "")


def slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


class Adapter:
    """One adapter per source site."""

    name: str = ""

    @staticmethod
    def matches(url: str) -> bool:
        raise NotImplementedError

    def resolve(self, url: str, client: httpx.Client) -> dict:
        """Return {'slug', 'name', 'source', 'attribution', 'urls': {index: url}}."""
        raise NotImplementedError


class ElviTarot(Adapter):
    """elvitarot.com/decks/tarot/<deck> — filenames are T{nn}_{CamelCaseName}.jpg
    under a per-deck path prefix discovered from the page's cover image."""

    name = "elvitarot"

    @staticmethod
    def matches(url: str) -> bool:
        return urlparse(url).netloc.endswith("elvitarot.com")

    def resolve(self, url: str, client: httpx.Client) -> dict:
        page = client.get(url)
        page.raise_for_status()
        m = re.search(r'(/_content/[^"\']+/images/tarot/[^"\'/]+)/', page.text)
        if not m:
            raise RuntimeError("could not find deck image path on page")
        base = f"https://{urlparse(url).netloc}{m.group(1)}"
        deck_slug = urlparse(url).path.rstrip("/").split("/")[-1]
        return {
            "slug": deck_slug,
            "name": slug_to_title(deck_slug),
            "source": url,
            "attribution": "Downloaded from elvitarot.com for personal use",
            "urls": {c.index: f"{base}/T{c.index:02d}_{camel(c.name)}.jpg" for c in CARDS},
        }


class TarotCom(Adapter):
    """tarot.com/tarot/decks/<deck> — gfx.tarot.com numeric images 0-77;
    full_size when available, else mid_size."""

    name = "tarot.com"

    @staticmethod
    def matches(url: str) -> bool:
        return urlparse(url).netloc.endswith("tarot.com")

    def resolve(self, url: str, client: httpx.Client) -> dict:
        deck_slug = urlparse(url).path.rstrip("/").split("/")[-1]
        size = "mid_size"
        for candidate in ("full_size", "mid_size"):
            probe = client.head(f"https://gfx.tarot.com/images/site/decks/{deck_slug}/{candidate}/0.jpg")
            if probe.status_code == 200:
                size = candidate
                break
        return {
            "slug": deck_slug,
            "name": slug_to_title(deck_slug),
            "source": url,
            "attribution": "Downloaded from tarot.com for personal use",
            "urls": {
                i: f"https://gfx.tarot.com/images/site/decks/{deck_slug}/{size}/{i}.jpg"
                for i in range(78)
            },
        }


class Meliorem(Adapter):
    """meliorem.info/cards/<deck>[/<card>] — numeric images 0-77 under /storage/cards/."""

    name = "meliorem"

    @staticmethod
    def matches(url: str) -> bool:
        return urlparse(url).netloc.endswith("meliorem.info")

    def resolve(self, url: str, client: httpx.Client) -> dict:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if not parts or parts[0] != "cards" or len(parts) < 2:
            raise RuntimeError("expected a meliorem.info/cards/<deck> URL")
        deck_slug = parts[1]
        return {
            "slug": deck_slug,
            "name": slug_to_title(deck_slug),
            "source": f"https://meliorem.info/cards/{deck_slug}",
            "attribution": "Downloaded from meliorem.info for personal use",
            "urls": {i: f"https://meliorem.info/storage/cards/{deck_slug}/{i}.jpg" for i in range(78)},
        }


# Wikimedia Commons filenames for the 1909 Rider-Waite-Smith scans (public domain).
_RWS_MAJORS = [
    "00_Fool", "01_Magician", "02_High_Priestess", "03_Empress", "04_Emperor",
    "05_Hierophant", "06_Lovers", "07_Chariot", "08_Strength", "09_Hermit",
    "10_Wheel_of_Fortune", "11_Justice", "12_Hanged_Man", "13_Death",
    "14_Temperance", "15_Devil", "16_Tower", "17_Star", "18_Moon", "19_Sun",
    "20_Judgement", "21_World",
]
_RWS_SUITS = ["Wands", "Cups", "Swords", "Pents"]


class WikimediaRWS(Adapter):
    """Built-in: public-domain Rider-Waite-Smith scans from Wikimedia Commons.
    Invoke with source 'rws'. Uses ?width= thumbnails — Commons rate-limits
    full-resolution originals hard (429) but serves cached thumbs freely."""

    name = "rws"
    width = 640  # standard Commons thumb bucket; ~200 KiB/card keeps a full deck bundleable

    @staticmethod
    def matches(url: str) -> bool:
        return url.strip().lower() == "rws"

    def resolve(self, url: str, client: httpx.Client) -> dict:
        fp = "https://commons.wikimedia.org/wiki/Special:FilePath"
        w = f"?width={self.width}"
        urls = {i: f"{fp}/RWS_Tarot_{name}.jpg{w}" for i, name in enumerate(_RWS_MAJORS)}
        for s, suit in enumerate(_RWS_SUITS):
            for r in range(14):
                urls[22 + s * 14 + r] = f"{fp}/{suit}{r + 1:02d}.jpg{w}"
        return {
            "slug": "rider-waite-smith",
            "name": "Rider–Waite–Smith",
            "source": "https://commons.wikimedia.org/wiki/Category:Rider-Waite_tarot_deck",
            "attribution": "Pamela Colman Smith, 1909 — public domain scans via Wikimedia Commons",
            "license": "Public domain",
            "urls": urls,
        }


class Template(Adapter):
    """Generic: a URL template with {n} (0-77) or {nn} (zero-padded) placeholders."""

    name = "template"

    @staticmethod
    def matches(url: str) -> bool:
        return "{n}" in url or "{nn}" in url

    def resolve(self, url: str, client: httpx.Client) -> dict:
        return {
            "slug": None,  # must come from --slug
            "name": None,
            "source": url,
            "attribution": None,
            "urls": {i: url.replace("{nn}", f"{i:02d}").replace("{n}", str(i)) for i in range(78)},
        }


ADAPTERS: list[type[Adapter]] = [WikimediaRWS, ElviTarot, TarotCom, Meliorem, Template]


def find_adapter(url: str) -> Adapter:
    for cls in ADAPTERS:
        if cls.matches(url):
            return cls()
    raise RuntimeError(
        f"no adapter for '{url}' — use --template 'https://…/{{n}}.jpg' for unknown sites"
    )
