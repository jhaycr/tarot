# tarot-slice

Cut a composition image — a sprite sheet, a photo of cards laid out on a table,
a marketing collage, or a printable PDF — into individual card images ready for
`tarot-dl <folder>` import.

```
pip install -e '.[slice]'        # numpy + pypdfium2; kept out of the runtime image
tarot-slice <image-or-pdf> <out-dir> [--strategy grid|segment|page] [options]
```

Slices are written in reading order (top-to-bottom, left-to-right) as
`<prefix>NN.png`. A raw composition carries no card identity — identify each
slice, rename it to a scheme `tarot.importer` recognizes (e.g.
`08-Major-Strength.png`, `Cups-Queen.png`), then import the folder with
`tarot-dl <dir> --name '...'`.

## Strategies

### `grid` — uniform card grids

Sprite sheets and contact sheets where every tile has the same size. Gutters
are auto-detected from low-variance pixel rows/columns; force the shape with
`--cols`/`--rows` when detection guesses wrong. `--trim 0.02` shaves a fraction
off each tile edge (bleed from neighbors).

```
tarot-slice sheet.png out/ --strategy grid --cols 10 --rows 3
```

Auto-detection assumes the card pitch is uniform. If the sheet's columns
drift (non-integer pitch, ragged tile widths in the output), force the shape —
and if the cards are separated by a plain background, `segment` may do better.

### `segment` — cards on a plain background

Photos or renders of separated cards on cork, paper, or a flat backdrop:
estimates the background color, finds connected components, de-rotates each
card (`--max-skew`, or `--no-deskew` for axis-aligned sources), trims edges,
and applies a rounded-corner alpha.

```
tarot-slice suit-photo.webp out/ --strategy segment
tarot-slice renders.png out/ --strategy segment --bg white --max-skew 25
```

Known-hard cases: cards that touch or overlap merge into one blob (detection
runs on a downscaled copy, so gaps of only a few pixels also merge — tightly
packed sheets are `grid` territory); white cards on a white background may
vanish. Hand-crop those.

### `page` — one card per page/image

Takes every page (or the single input image) whole. This is the shape of
purchased printable-PDF decks. Needs neither numpy nor a grid guess.

```
tarot-slice deck.pdf out/ --strategy page
```

## PDF input

Any strategy accepts a `.pdf` input: each page is rasterized at `--dpi`
(default 300) and fed to the strategy, with continuous slice numbering across
pages. `page` for one-card-per-page decks, `grid` for print-and-play sheets.

```
tarot-slice sheets.pdf out/ --strategy grid --cols 3 --rows 3 --dpi 300
```

## Options reference

Run `tarot-slice --help` for the full list: `--prefix`, `--dpi`, grid's
`--cols/--rows/--trim`, and segment's `--bg/--bg-tol/--open/--pad/
--max-skew/--no-deskew/--round-frac`.
