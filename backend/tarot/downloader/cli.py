"""tarot-dl: download or import a deck into the decks folder.

Examples:
    tarot-dl rws                      # or 'marseille' for the Dodal trumps
    tarot-dl https://elvitarot.com/decks/tarot/modern-witch-tarot
    tarot-dl 'https://example.com/deck/{n}.jpg' --slug my-deck --name 'My Deck'
    tarot-dl ~/Pictures/Tarot/Stick --name 'Stick Figure Tarot'   # local folder import

Local imports map filenames by card name/suit/rank (see tarot.importer).
Downloaded decks are for personal use.
"""

import argparse
import io
import re
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
    on_start=None,  # called once with (slug, name, total) after the source resolves
    on_card=None,  # called after each card with (index, ok)
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

    total = len(info["urls"])
    print(f"deck: {name} ({slug}, {total} cards)")
    print(f"dest: {deck_dir}")
    if on_start:
        on_start(slug, name, total)

    failures: list[int] = []
    for card in CARDS:
        url = info["urls"].get(card.index)
        if url is None:
            continue  # partial deck (e.g. majors-only sources)
        existing = list(cards_dir.glob(f"{card.index:02d}.*"))
        if existing and not force:
            print(f"  [{card.index:02d}] {card.name}: exists, skipping")
            if on_card:
                on_card(card.index, True)
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
        if on_card:
            on_card(card.index, card.index not in failures)
        time.sleep(delay)

    if info.get("back_url") and not list(deck_dir.glob("back.*")):
        try:
            resp = client.get(info["back_url"])
            resp.raise_for_status()
            ext = EXT_BY_TYPE.get(resp.headers.get("content-type", "").split(";")[0].strip(), ".jpg")
            (deck_dir / f"back{ext}").write_bytes(resp.content)
            print("  [back] card back downloaded")
        except Exception as e:
            print(f"  [back] FAILED — {e}", file=sys.stderr)

    manifest = {
        "name": name,
        "source": info.get("source"),
        "attribution": info.get("attribution"),
        "license": info.get("license"),
    }
    (deck_dir / "manifest.yaml").write_text(
        yaml.safe_dump({k: v for k, v in manifest.items() if v}, sort_keys=False, allow_unicode=True)
    )

    got = total - len(failures)
    print(f"\n{got}/{total} cards downloaded" + (f", failed: {failures}" if failures else ""))
    if failures:
        print("re-run the same command to retry the failed cards")
    return deck_dir


def import_dir(
    src: Path,
    dest_root: Path,
    slug: str | None = None,
    name: str | None = None,
    max_width: int | None = None,
) -> Path:
    from tarot.decks import IMAGE_EXTS
    from tarot.importer import map_filenames

    files = {}
    for f in sorted(src.iterdir()):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            files.setdefault(f.stem, f)
    mapping, back_stem, problems = map_filenames(list(files))
    for p in problems:
        print(f"  ! {p}", file=sys.stderr)
    if len(mapping) < 22:
        raise SystemExit(f"error: only recognized {len(mapping)} cards in {src}")

    name = name or src.name
    slug = slug or re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
    deck_dir = dest_root / slug
    cards_dir = deck_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)

    for index, stem in sorted(mapping.items()):
        f = files[stem]
        data = f.read_bytes()
        ext = f.suffix.lower()
        if max_width:
            data, new_ext = shrink(data, max_width)
            ext = new_ext or ext
        (cards_dir / f"{index:02d}{ext}").write_bytes(data)
    if back_stem:
        f = files[back_stem]
        (deck_dir / f"back{f.suffix.lower()}").write_bytes(f.read_bytes())
    src_extras = src / "extras"
    if src_extras.is_dir():
        (deck_dir / "extras").mkdir(exist_ok=True)
        n = 0
        for f in sorted(src_extras.iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                (deck_dir / "extras" / f.name).write_bytes(f.read_bytes())
                n += 1
        if n:
            print(f"  + {n} extra cards")

    (deck_dir / "manifest.yaml").write_text(
        yaml.safe_dump({"name": name, "attribution": f"Imported from {src}"}, sort_keys=False, allow_unicode=True)
    )
    kind = "majors only" if len(mapping) == 22 and all(i < 22 for i in mapping) else f"{len(mapping)}/78"
    print(f"imported {name} ({slug}): {kind}" + (", with back" if back_stem else ""))
    return deck_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tarot-dl",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="deck page URL, 'rws'/'marseille', a URL template with {n}/{nn}, or a local folder")
    parser.add_argument("--slug", help="deck folder name (default: derived from source)")
    parser.add_argument("--name", help="display name (default: derived from slug)")
    parser.add_argument("--dest", type=Path, default=None, help=f"decks root (default: {user_decks_dir()})")
    parser.add_argument("--user", help="download into this user's private deck collection")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests (default 0.5)")
    parser.add_argument("--force", action="store_true", help="re-download existing cards")
    parser.add_argument("--max-width", type=int, default=None, help="downscale images wider than this many pixels")
    args = parser.parse_args()

    src_path = Path(args.source).expanduser()
    if src_path.is_dir():
        deck_dir = import_dir(
            src_path,
            args.dest or user_decks_dir(args.user),
            slug=args.slug,
            name=args.name,
            max_width=args.max_width,
        )
        from tarot.dedupe import dedupe_deck

        shared = dedupe_deck(deck_dir)
        if shared:
            print(f"{shared} images deduplicated against existing decks")
        return

    try:
        deck_dir = download_deck(
            args.source,
            args.dest or user_decks_dir(args.user),
            slug=args.slug,
            name=args.name,
            delay=args.delay,
            force=args.force,
            max_width=args.max_width,
        )
        from tarot.dedupe import dedupe_deck

        shared = dedupe_deck(deck_dir)
        if shared:
            print(f"{shared} images deduplicated against existing decks")
    except (RuntimeError, httpx.HTTPError) as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
