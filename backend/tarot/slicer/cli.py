"""tarot-slice: cut a composition image into individual card images.

Examples:
    # uniform grid (auto-detected, or force the shape)
    tarot-slice sheet.png out/ --strategy grid --cols 7 --rows 2 --trim 0.02

    # cards laid/fanned on a plain background (cork, paper, render backdrop)
    tarot-slice suit-photo.webp out/ --strategy segment
    tarot-slice renders.png out/ --strategy segment --bg white --max-skew 25

Slices are written in reading order as <prefix>NN.png. Identify and rename them
to the deck naming scheme (e.g. 08-Major-Strength.png), then import with
`tarot-dl <folder> --name '...'`. Needs the [slice] extra: pip install -e '.[slice]'
"""

import argparse
import sys
from pathlib import Path

from PIL import Image


def slice_to_dir(
    image: Path,
    out_dir: Path,
    strategy: str,
    opt,
    prefix: str = "slice_",
    on_start=None,  # (strategy, total) once the slices are known
    on_card=None,  # (i, ok) after each slice is written
) -> list[Path]:
    from tarot.slicer.core import slice_image

    img = Image.open(image)
    cards = slice_image(img, strategy, opt)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(cards)
    print(f"strategy: {strategy}  ->  {total} slice(s)")
    print(f"dest: {out_dir}")
    if on_start:
        on_start(strategy, total)

    written: list[Path] = []
    for i, card in enumerate(cards):
        path = out_dir / f"{prefix}{i:02d}.png"
        try:
            card.save(path)
            w, h = card.size
            print(f"  [{i:02d}] {w}x{h} -> {path.name}")
            written.append(path)
            ok = True
        except Exception as e:  # pragma: no cover - disk errors
            print(f"  [{i:02d}] FAILED — {e}", file=sys.stderr)
            ok = False
        if on_card:
            on_card(i, ok)

    print(f"\n{len(written)}/{total} slices written")
    if total:
        print("next: identify each slice and rename to the deck scheme, then `tarot-dl <dir>`")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tarot-slice",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", type=Path, help="composition image to slice")
    parser.add_argument("out_dir", type=Path, help="directory for the slices")
    parser.add_argument("--strategy", choices=["grid", "segment"], default="grid")
    parser.add_argument("--prefix", default="slice_", help="output filename prefix")
    # grid
    parser.add_argument("--cols", type=int, help="grid: force column count")
    parser.add_argument("--rows", type=int, help="grid: force row count")
    parser.add_argument("--trim", type=float, default=0.0, help="grid: fraction to shave off each tile edge")
    # segment
    parser.add_argument("--bg", default="auto", help="segment: background as 'auto', 'white', or '#rrggbb'")
    parser.add_argument("--bg-tol", type=float, default=32.0, help="segment: colour distance for foreground")
    parser.add_argument("--open", type=int, default=1, dest="open_iters", help="segment: morphological opening passes (speckle/bridge cleanup)")
    parser.add_argument("--pad", type=int, default=8, help="segment: px of context kept before de-rotating")
    parser.add_argument("--max-skew", type=float, default=20.0, help="segment: max de-rotation angle (deg)")
    parser.add_argument("--no-deskew", action="store_true", help="segment: skip de-rotation")
    parser.add_argument("--round-frac", type=float, default=0.055, help="segment: corner radius frac (0 disables)")
    args = parser.parse_args()

    try:
        from tarot.slicer.core import Options
    except ImportError as e:  # numpy missing
        raise SystemExit(f"error: the slicer needs the [slice] extra ({e}); run: pip install -e '.[slice]'")

    opt = Options(
        cols=args.cols,
        rows=args.rows,
        trim=args.trim,
        bg=args.bg,
        bg_tol=args.bg_tol,
        open_iters=args.open_iters,
        pad=args.pad,
        deskew=not args.no_deskew,
        max_skew=args.max_skew,
        round_frac=args.round_frac,
    )
    try:
        slice_to_dir(args.image, args.out_dir, args.strategy, opt, prefix=args.prefix)
    except (ValueError, OSError) as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
