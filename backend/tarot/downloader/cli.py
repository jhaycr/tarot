"""tarot-dl: download a full 78-card deck into the decks folder.

Examples:
    tarot-dl rws
    tarot-dl https://elvitarot.com/decks/tarot/modern-witch-tarot
    tarot-dl https://www.tarot.com/tarot/decks/8-bit
    tarot-dl 'https://example.com/deck/{n}.jpg' --slug my-deck --name 'My Deck'

Downloaded decks are for personal use.
"""

import argparse
import io
import sys
import time
from pathlib import Path

import httpx
import yaml
from PIL import Image

from tarot.cards import CARDS
from tarot.decks import user_decks_dir
from tarot.downloader.adapters import find_adapter

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) tarot-dl/0.1 (personal archival)"

EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def shrink(data: bytes, max_width: int) -> tuple[bytes, str]:
    """Downscale to max_width if wider; returns (bytes, ext)."""
    img = Image.open(io.BytesIO(data))
    if img.width <= max_width:
        return data, ""
    img = img.convert("RGB")
    img.thumbnail((max_width, max_width * 4), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=87, optimize=True)
    return out.getvalue(), ".jpg"


def download_deck(
    source: str,
    dest_root: Path,
    slug: str | None = None,
    name: str | None = None,
    delay: float = 0.5,
    force: bool = False,
    max_width: int | None = None,
) -> Path:
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )
    adapter = find_adapter(source)
    info = adapter.resolve(source, client)

    slug = slug or info["slug"]
    if not slug:
        raise SystemExit("this source needs an explicit --slug")
    name = name or info["name"] or slug

    deck_dir = dest_root / slug
    cards_dir = deck_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)

    print(f"deck: {name} ({slug})")
    print(f"dest: {deck_dir}")

    failures: list[int] = []
    for card in CARDS:
        url = info["urls"][card.index]
        existing = list(cards_dir.glob(f"{card.index:02d}.*"))
        if existing and not force:
            print(f"  [{card.index:02d}] {card.name}: exists, skipping")
            continue
        try:
            resp = client.get(url)
            for attempt in range(3):
                if resp.status_code != 429:
                    break
                wait = float(resp.headers.get("retry-after", 15))
                print(f"  [{card.index:02d}] rate limited, waiting {wait:.0f}s…")
                time.sleep(wait)
                resp = client.get(url)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "").split(";")[0].strip()
            ext = EXT_BY_TYPE.get(ctype)
            if not ext:
                raise RuntimeError(f"not an image (content-type: {ctype or 'unknown'})")
            data = resp.content
            if max_width:
                data, new_ext = shrink(data, max_width)
                ext = new_ext or ext
            out = cards_dir / f"{card.index:02d}{ext}"
            out.write_bytes(data)
            print(f"  [{card.index:02d}] {card.name}: {len(data) // 1024} KiB")
        except Exception as e:
            failures.append(card.index)
            print(f"  [{card.index:02d}] {card.name}: FAILED — {e}", file=sys.stderr)
        time.sleep(delay)

    manifest = {
        "name": name,
        "source": info.get("source"),
        "attribution": info.get("attribution"),
        "license": info.get("license"),
    }
    (deck_dir / "manifest.yaml").write_text(
        yaml.safe_dump({k: v for k, v in manifest.items() if v}, sort_keys=False, allow_unicode=True)
    )

    got = 78 - len(failures)
    print(f"\n{got}/78 cards downloaded" + (f", failed: {failures}" if failures else ""))
    if failures:
        print("re-run the same command to retry the failed cards")
    return deck_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tarot-dl",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="deck page URL, 'rws', or a URL template with {n}/{nn}")
    parser.add_argument("--slug", help="deck folder name (default: derived from source)")
    parser.add_argument("--name", help="display name (default: derived from slug)")
    parser.add_argument("--dest", type=Path, default=None, help=f"decks root (default: {user_decks_dir()})")
    parser.add_argument("--user", help="download into this user's private deck collection")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests (default 0.5)")
    parser.add_argument("--force", action="store_true", help="re-download existing cards")
    parser.add_argument("--max-width", type=int, default=None, help="downscale images wider than this many pixels")
    args = parser.parse_args()

    try:
        download_deck(
            args.source,
            args.dest or user_decks_dir(args.user),
            slug=args.slug,
            name=args.name,
            delay=args.delay,
            force=args.force,
            max_width=args.max_width,
        )
    except (RuntimeError, httpx.HTTPError) as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
