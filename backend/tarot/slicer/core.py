"""Slicing strategies: composition image -> list of individual card images.

Two strategies, mirroring how the downloader has per-site adapters:

- ``grid``    uniform card grids; cuts on low-variance gutters (or explicit
              --cols/--rows). Ported from the original tools/slice_grid.py.
- ``segment`` cards laid on a plain background (cork, paper, a flat render
              backdrop): estimate the background colour, band the foreground
              into rows then cards, brute-force de-rotate each card by the
              angle that minimises its bounding box, edge-trim, and apply a
              rounded-corner alpha. This reconstructs the ad-hoc pipeline that
              extracted the Solarpunk deck (see docs/handoffs) as reusable code.

Slices come out in reading order (top-to-bottom, left-to-right). Mapping them to
canonical card indices is downstream work (eye + tarot.importer) — a raw
composition image carries no identity, unlike a downloader source.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

# A colour very unlikely to occur in card art, used as the fill when rotating so
# the rotated-in corners can be told apart from real background/foreground.
_SENTINEL = (1, 254, 1)


@dataclass
class Options:
    # grid
    cols: int | None = None
    rows: int | None = None
    trim: float = 0.0  # fraction shaved off each grid tile edge
    # segment
    bg: str = "auto"  # 'auto' (sample the border), 'white', or '#rrggbb'
    bg_tol: float = 32.0  # floor for the foreground colour-distance threshold
    min_area_frac: float = 0.004  # blobs smaller than this fraction of the image are dropped
    open_iters: int = 1  # morphological opening passes: kill speckle + thin background bridges
    pad: int = 8  # px of context kept around each card before de-rotating
    deskew: bool = True
    max_skew: float = 20.0  # degrees searched either side of upright
    round_frac: float = 0.055  # corner radius as a fraction of min(w,h); 0=off


# Detection runs on a downscaled copy so background texture (cork grain, paper
# fibre, JPEG noise) averages out and connected components stays cheap.
_SEG_TARGET = 360


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def _as_rgb(img: Image.Image) -> Image.Image:
    return img if img.mode == "RGB" else img.convert("RGB")


def parse_bg(spec: str, arr: np.ndarray) -> np.ndarray:
    """Resolve the background colour to an RGB float triple."""
    spec = spec.strip().lower()
    if spec == "white":
        return np.array([255.0, 255.0, 255.0])
    if spec.startswith("#") and len(spec) == 7:
        return np.array([int(spec[i : i + 2], 16) for i in (1, 3, 5)], dtype=float)
    # 'auto': median of a border ring — the frame is almost all background
    h, w, _ = arr.shape
    ring = max(2, round(min(h, w) * 0.03))
    border = np.concatenate(
        [
            arr[:ring].reshape(-1, 3),
            arr[-ring:].reshape(-1, 3),
            arr[:, :ring].reshape(-1, 3),
            arr[:, -ring:].reshape(-1, 3),
        ]
    )
    return np.median(border, axis=0)


def foreground_mask(arr: np.ndarray, bg: np.ndarray, tol: float) -> np.ndarray:
    """Boolean mask: pixels whose colour is far enough from the background."""
    dist = np.sqrt(((arr - bg) ** 2).sum(axis=2))
    return dist > tol


def _runs(on: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Spans of consecutive True at least min_len long."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                spans.append((start, i))
            start = None
    if start is not None and len(on) - start >= min_len:
        spans.append((start, len(on)))
    return spans


def _tight_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def round_corners(card: Image.Image, radius: int) -> Image.Image:
    """Apply a rounded-rectangle alpha so background never shows at the corners."""
    card = card.convert("RGBA")
    w, h = card.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    card.putalpha(mask)
    return card


# --------------------------------------------------------------------------- #
# grid strategy
# --------------------------------------------------------------------------- #
def _gutters(profile: np.ndarray, min_run: int = 2) -> list[tuple[int, int]]:
    thresh = np.percentile(profile, 20) + 1e-6
    return _runs(profile < thresh, min_run)


def _split_even(size: int, n: int) -> list[tuple[int, int]]:
    edges = [round(i * size / n) for i in range(n + 1)]
    return list(zip(edges[:-1], edges[1:]))


def slice_grid(img: Image.Image, opt: Options) -> list[Image.Image]:
    img = _as_rgb(img)
    arr = np.asarray(img, dtype=np.float32)
    w, h = img.size

    if opt.cols and opt.rows:
        col_spans = _split_even(w, opt.cols)
        row_spans = _split_even(h, opt.rows)
    else:
        col_gaps = _gutters(arr.std(axis=(0, 2)))
        row_gaps = _gutters(arr.std(axis=(1, 2)))
        if not col_gaps or not row_gaps:
            raise ValueError("could not auto-detect a grid; pass --cols/--rows")

        def spans(gaps, size):
            cuts = [0] + [(a + b) // 2 for a, b in gaps] + [size]
            return [(a, b) for a, b in zip(cuts[:-1], cuts[1:]) if b - a > size * 0.04]

        col_spans, row_spans = spans(col_gaps, w), spans(row_gaps, h)

    out: list[Image.Image] = []
    for y0, y1 in row_spans:
        for x0, x1 in col_spans:
            tx = int((x1 - x0) * opt.trim)
            ty = int((y1 - y0) * opt.trim)
            out.append(img.crop((x0 + tx, y0 + ty, x1 - tx, y1 - ty)))
    return out


# --------------------------------------------------------------------------- #
# segment strategy
# --------------------------------------------------------------------------- #
def _deskew(crop: Image.Image, bg: np.ndarray, tol: float, opt: Options) -> Image.Image:
    """Rotate to the angle that minimises the card's bounding box, then crop it.

    The card's foreground mask is measured on a downscaled copy (denoised, and
    ~ the same threshold used for detection) so background texture doesn't
    inflate the box; the winning angle/box is then applied at full resolution.
    """
    dscale = max(1.0, max(crop.size) / 200)

    def measure(angle: float):
        rot = crop.rotate(angle, expand=True, fillcolor=_SENTINEL, resample=Image.BICUBIC)
        sw, sh = max(1, round(rot.width / dscale)), max(1, round(rot.height / dscale))
        a = np.asarray(rot.resize((sw, sh), Image.BOX), dtype=np.float32)
        sentinel = (np.abs(a - _SENTINEL) < 24).all(axis=2)
        fg = (np.sqrt(((a - bg) ** 2).sum(axis=2)) > tol) & ~sentinel
        bb = _tight_bbox(fg)
        area = float("inf") if bb is None else (bb[2] - bb[0]) * (bb[3] - bb[1])
        return area, rot, bb

    m = int(opt.max_skew)
    best = min(range(-m, m + 1, 2), key=lambda a: measure(a)[0])
    best = min((best + d * 0.5 for d in range(-3, 4)), key=lambda a: measure(a)[0])

    _, rot, bb = measure(best)
    if not bb:
        return rot
    # bb is in downscaled coords → back to the rotated full-res image
    return rot.crop((int(bb[0] * dscale), int(bb[1] * dscale),
                     min(rot.width, int(bb[2] * dscale)), min(rot.height, int(bb[3] * dscale))))


def _background_threshold(ring_dist: np.ndarray, floor: float) -> float:
    """Separate background from cards, tracking the background's own noise. Kept
    below the extreme tail so muted card regions aren't mistaken for background;
    residual speckle is handled by morphological opening + the min-area filter."""
    return max(floor, float(np.percentile(ring_dist, 90)))


def _erode(m: np.ndarray) -> np.ndarray:
    e = m.copy()
    e[1:] &= m[:-1]
    e[:-1] &= m[1:]
    e[:, 1:] &= m[:, :-1]
    e[:, :-1] &= m[:, 1:]
    return e


def _dilate(m: np.ndarray) -> np.ndarray:
    d = m.copy()
    d[1:] |= m[:-1]
    d[:-1] |= m[1:]
    d[:, 1:] |= m[:, :-1]
    d[:, :-1] |= m[:, 1:]
    return d


def _open(m: np.ndarray, iters: int) -> np.ndarray:
    """Erode then dilate (4-connectivity): removes speckle and hairline bridges
    without shrinking solid card bodies."""
    for _ in range(iters):
        m = _erode(m)
    for _ in range(iters):
        m = _dilate(m)
    return m


def _components(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int]]:
    """4-connected component bounding boxes (x0, y0, x1, y1), largest first.

    Runs on the downscaled mask, so a plain Python flood fill is cheap.
    """
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    boxes: list[tuple[int, int, int, int, int]] = []  # area + bbox
    for sy in range(h):
        row = mask[sy]
        for sx in range(w):
            if not row[sx] or seen[sy, sx]:
                continue
            seen[sy, sx] = True
            stack = [(sy, sx)]
            x0 = x1 = sx
            y0 = y1 = sy
            area = 0
            while stack:
                y, x = stack.pop()
                area += 1
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if area >= min_area:
                boxes.append((area, x0, y0, x1 + 1, y1 + 1))
    boxes.sort(reverse=True)
    return [b[1:] for b in boxes]


def slice_segment(img: Image.Image, opt: Options) -> list[Image.Image]:
    img = _as_rgb(img)
    W, H = img.size

    # detect on a downscaled copy: texture averages out, components stay cheap
    scale = max(1.0, max(W, H) / _SEG_TARGET)
    sw, sh = max(1, round(W / scale)), max(1, round(H / scale))
    small = np.asarray(img.resize((sw, sh), Image.BOX), dtype=np.float32)
    bg = parse_bg(opt.bg, small)

    dist = np.sqrt(((small - bg) ** 2).sum(axis=2))
    ring = max(2, round(min(sh, sw) * 0.03))
    ring_dist = np.concatenate([dist[:ring].ravel(), dist[-ring:].ravel(),
                                dist[:, :ring].ravel(), dist[:, -ring:].ravel()])
    tol = opt.bg_tol if opt.bg != "auto" else _background_threshold(ring_dist, opt.bg_tol)
    mask = _open(dist > tol, opt.open_iters)

    min_area = max(16, int(opt.min_area_frac * sw * sh))
    boxes = _components(mask, min_area)

    # reading order: group into rows by vertical centre, then left-to-right
    if boxes:
        row_h = float(np.median([y1 - y0 for _, y0, _, y1 in boxes]))
        boxes.sort(key=lambda b: (round((b[1] + b[3]) / 2 / max(1.0, row_h * 0.6)), b[0]))

    cards: list[Image.Image] = []
    for x0, y0, x1, y1 in boxes:
        # back to full-res coordinates, with padding for the de-rotation search
        fx0 = max(0, int(x0 * scale) - opt.pad)
        fy0 = max(0, int(y0 * scale) - opt.pad)
        fx1 = min(W, int(x1 * scale) + opt.pad)
        fy1 = min(H, int(y1 * scale) + opt.pad)
        crop = img.crop((fx0, fy0, fx1, fy1))
        card = _deskew(crop, bg, tol, opt) if opt.deskew else crop
        if opt.round_frac > 0:
            card = round_corners(card, int(min(card.size) * opt.round_frac))
        cards.append(card)
    return cards


STRATEGIES = {"grid": slice_grid, "segment": slice_segment}


def slice_image(img: Image.Image, strategy: str, opt: Options) -> list[Image.Image]:
    try:
        fn = STRATEGIES[strategy]
    except KeyError:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {list(STRATEGIES)}")
    return fn(img, opt)
