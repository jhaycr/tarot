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


class MarseilleDodal(Adapter):
    """Built-in: Jean Dodal Tarot de Marseille trumps (c. 1701, public domain)
    from Wikimedia Commons — a majors-only deck. Invoke with source 'marseille'.

    Marseilles numbering has Justice as VIII and Strength (La Force) as XI —
    swapped relative to the RWS-based canonical index — so trumps are mapped
    by card identity, not by their printed number.
    """

    name = "marseille"
    width = 640

    @staticmethod
    def matches(url: str) -> bool:
        return url.strip().lower() in ("marseille", "marseilles", "dodal")

    def resolve(self, url: str, client: httpx.Client) -> dict:
        fp = "https://commons.wikimedia.org/wiki/Special:FilePath"
        w = f"?width={self.width}"

        def trump(n: int) -> str:
            return f"{fp}/Jean_Dodal_Tarot_trump_{n:02d}.jpg{w}"

        urls = {0: f"{fp}/Jean_Dodal_Tarot_trump_Fool.jpg{w}"}
        for i in range(1, 22):
            if i == 8:
                urls[i] = trump(11)  # La Force (Strength)
            elif i == 11:
                urls[i] = trump(8)  # La Justice
            else:
                urls[i] = trump(i)
        return {
            "slug": "marseille-dodal",
            "name": "Tarot de Marseille (Dodal)",
            "source": "https://commons.wikimedia.org/wiki/Category:Tarot_de_Marseille_-_Jean_Dodal",
            "attribution": "Jean Dodal, Lyon c. 1701 — public domain scans via Wikimedia Commons",
            "license": "Public domain",
            "back_url": f"{fp}/Jean_Dodal_Tarot_reverse.jpg{w}",
            "urls": urls,
        }


class FandomWiki(Adapter):
    """<wiki>.fandom.com/wiki/<Page-or-Category> — enumerate the page's images
    via the MediaWiki API (page images, or category file members for
    Category: titles), resolve original-file URLs on static.wikia.nocookie.net,
    and map filenames onto canonical indices by card NAME (tarot.importer).

    Fandom's CDN content-negotiates PNGs into WebP; '?format=original' pins the
    true file. Works for e.g. the Cyberpunk 2077 tarot page and the
    Megami Tensei wiki's Persona card categories.
    """

    name = "fandom"

    @staticmethod
    def matches(url: str) -> bool:
        return urlparse(url).netloc.endswith(".fandom.com")

    @staticmethod
    def _api(client: httpx.Client, root: str, **params) -> dict:
        resp = client.get(f"{root}/api.php", params={"format": "json", **params})
        resp.raise_for_status()
        return resp.json()

    def _files(self, client: httpx.Client, root: str, title: str) -> dict[str, str]:
        """{file title: original url} for every image on the page/category."""
        out: dict[str, str] = {}
        if title.lower().startswith("category:"):
            cont: dict = {}
            while True:
                data = self._api(
                    client, root, action="query", generator="categorymembers",
                    gcmtitle=title, gcmtype="file", gcmlimit="500",
                    prop="imageinfo", iiprop="url", **cont,
                )
                for page in data.get("query", {}).get("pages", {}).values():
                    info = page.get("imageinfo")
                    if info:
                        out[page["title"]] = info[0]["url"]
                cont = data.get("continue", {})
                if not cont:
                    return out
        titles: list[str] = []
        cont = {}
        while True:
            data = self._api(
                client, root, action="query", titles=title,
                prop="images", imlimit="500", **cont,
            )
            for page in data.get("query", {}).get("pages", {}).values():
                titles += [im["title"] for im in page.get("images", [])]
            cont = data.get("continue", {})
            if not cont:
                break
        for i in range(0, len(titles), 50):
            data = self._api(
                client, root, action="query", titles="|".join(titles[i : i + 50]),
                prop="imageinfo", iiprop="url",
            )
            for page in data.get("query", {}).get("pages", {}).values():
                info = page.get("imageinfo")
                if info:
                    out[page["title"]] = info[0]["url"]
        return out

    def resolve(self, url: str, client: httpx.Client) -> dict:
        import sys

        from tarot.importer import map_filenames

        parsed = urlparse(url)
        root = f"https://{parsed.netloc}"
        m = re.search(r"/wiki/([^?#]+)", parsed.path)
        if not m:
            raise RuntimeError("expected a …fandom.com/wiki/<Page> URL")
        title = m.group(1).replace("_", " ")

        files = self._files(client, root, title)
        by_stem: dict[str, str] = {}
        for file_title, file_url in files.items():
            # 'File:TarotCard 01 TheFool.png' — the URL path ends in /revision/latest,
            # so the filename must come from the title.
            stem, dot, ext = file_title.split(":", 1)[-1].rpartition(".")
            if dot and f".{ext.lower()}" in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                by_stem.setdefault(stem, file_url + ("&" if "?" in file_url else "?") + "format=original")
        if not by_stem:
            raise RuntimeError(f"no images found on {title}")

        mapping, back_stem, _cover_stem, problems = map_filenames(list(by_stem))
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        if not mapping:
            raise RuntimeError("no filenames mapped onto tarot cards — see warnings above")
        wiki = parsed.netloc.split(".")[0]
        page_slug = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-")
        return {
            "slug": f"{wiki}-{page_slug}"[:60].rstrip("-"),
            "name": slug_to_title(page_slug),
            "source": url,
            "attribution": f"Game art via {parsed.netloc} for personal use",
            "back_url": by_stem[back_stem] if back_stem else None,
            "urls": {index: by_stem[stem] for index, stem in mapping.items()},
        }


class Wayback(Adapter):
    """web.archive.org/web/<timestamp>/<original> — a snapshot of a gallery
    page whose linked/embedded images are card scans. Collects image links,
    rewrites them to the snapshot's raw 'im_' form, and maps filenames onto
    canonical indices by card NAME (tarot.importer). Serves any dead-site
    gallery, e.g. the original lunarbistro.com 8-Bit Tarot pages."""

    name = "wayback"

    @staticmethod
    def matches(url: str) -> bool:
        return urlparse(url).netloc == "web.archive.org"

    def resolve(self, url: str, client: httpx.Client) -> dict:
        import sys
        from posixpath import basename
        from urllib.parse import urljoin

        from tarot.importer import map_filenames

        m = re.match(r"https?://web\.archive\.org/web/(\d+)[a-z_]*/(.+)", url)
        if not m:
            raise RuntimeError("expected a web.archive.org/web/<timestamp>/<url> snapshot URL")
        ts, orig = m.groups()

        page = client.get(f"https://web.archive.org/web/{ts}/{orig}")
        page.raise_for_status()

        by_stem: dict[str, str] = {}
        for link in re.findall(
            r"""(?:src|href)=["']([^"']+\.(?:jpe?g|png|gif|webp))["']""", page.text, re.I
        ):
            wb = re.match(r"(?:https?://web\.archive\.org)?/web/\d+[a-z_]*/(.+)", link)
            absolute = wb.group(1) if wb else urljoin(orig, link)
            stem = basename(urlparse(absolute).path).rpartition(".")[0]
            if stem:
                by_stem.setdefault(stem, f"https://web.archive.org/web/{ts}im_/{absolute}")
        if not by_stem:
            raise RuntimeError("no image links found in the snapshot")

        mapping, back_stem, _cover_stem, problems = map_filenames(list(by_stem))
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        if not mapping:
            raise RuntimeError("no filenames mapped onto tarot cards — see warnings above")
        tail = [p for p in urlparse(orig).path.split("/") if p]
        page_slug = re.sub(r"[^a-z0-9-]+", "-", (tail[-1].rpartition(".")[0] or tail[-1]) if tail else "").strip("-")
        return {
            "slug": page_slug or None,  # fall back to --slug for bare-domain snapshots
            "name": slug_to_title(page_slug) if page_slug else None,
            "source": url,
            "attribution": f"Archived from {urlparse(orig).netloc} (Wayback Machine) for personal use",
            "back_url": by_stem[back_stem] if back_stem else None,
            "urls": {index: by_stem[stem] for index, stem in mapping.items()},
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


ADAPTERS: list[type[Adapter]] = [
    WikimediaRWS, MarseilleDodal, ElviTarot, TarotCom, Meliorem, FandomWiki, Wayback, Template,
]


def find_adapter(url: str) -> Adapter:
    for cls in ADAPTERS:
        if cls.matches(url):
            return cls()
    raise RuntimeError(
        f"no adapter for '{url}' — use --template 'https://…/{{n}}.jpg' for unknown sites"
    )
