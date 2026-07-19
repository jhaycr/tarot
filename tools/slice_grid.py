"""Slice a tarot-card grid image into individual card images.

Usage: python slice_grid.py <image> <out_dir> [--cols N --rows N]
Without explicit dimensions, tries to auto-detect the grid by finding
low-variance gutter rows/columns (works for uniform grids on flat gaps).
Cards are written as slice_r{r}c{c}.png for later identification/mapping.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def gutters(profile: np.ndarray, min_run: int = 2) -> list[tuple[int, int]]:
    """Runs of indices whose variance is well below typical — candidate gaps."""
    thresh = np.percentile(profile, 20) + 1e-6
    mask = profile < thresh
    runs = []
    start = None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if i - start >= min_run:
                runs.append((start, i))
            start = None
    if start is not None and len(mask) - start >= min_run:
        runs.append((start, len(mask)))
    return runs


def split_even(size: int, n: int) -> list[tuple[int, int]]:
    edges = [round(i * size / n) for i in range(n + 1)]
    return list(zip(edges[:-1], edges[1:]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("out_dir")
    ap.add_argument("--cols", type=int)
    ap.add_argument("--rows", type=int)
    ap.add_argument("--trim", type=float, default=0.0, help="fraction to trim from each slice edge")
    args = ap.parse_args()

    img = Image.open(args.image).convert("RGB")
    arr = np.asarray(img, dtype=np.float32)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if args.cols and args.rows:
        col_spans = split_even(img.width, args.cols)
        row_spans = split_even(img.height, args.rows)
    else:
        # variance across each column/row of pixels; gutters are flat
        col_var = arr.std(axis=(0, 2))
        row_var = arr.std(axis=(1, 2))
        col_gaps = gutters(col_var)
        row_gaps = gutters(row_var)
        print(f"detected {len(col_gaps)} column gaps, {len(row_gaps)} row gaps", file=sys.stderr)
        if len(col_gaps) < 1 or len(row_gaps) < 1:
            sys.exit("could not auto-detect grid; pass --cols/--rows")

        def spans(gaps, size):
            cuts = [0] + [(a + b) // 2 for a, b in gaps] + [size]
            return [(a, b) for a, b in zip(cuts[:-1], cuts[1:]) if b - a > size * 0.04]

        col_spans = spans(col_gaps, img.width)
        row_spans = spans(row_gaps, img.height)

    n = 0
    for r, (y0, y1) in enumerate(row_spans):
        for c, (x0, x1) in enumerate(col_spans):
            tw, th = (x1 - x0), (y1 - y0)
            tx, ty = int(tw * args.trim), int(th * args.trim)
            tile = img.crop((x0 + tx, y0 + ty, x1 - tx, y1 - ty))
            tile.save(out / f"slice_r{r}c{c}.png")
            n += 1
    print(f"{n} slices ({len(row_spans)} rows × {len(col_spans)} cols) -> {out}")


if __name__ == "__main__":
    main()
