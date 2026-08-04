"""Guidebook PDF import: segment a book into card passages + essay chunks.

Two lanes, auto-selected by text-layer presence:

- Lane A (text-layer PDFs): pypdfium2 text + per-line font sizes; heading
  candidates from the PDF outline and oversized lines; card names matched by
  importer.classify_heading. If the deterministic pass can't account for the
  deck (< 22 distinct cards), ONE small LLM call maps the ambiguous heading
  list (never full book text) to indices.

- Lane B (image-only PDFs — the common Etsy case, 7-for-7 in the validation
  corpus): every page is rendered and a vision-capable model transcribes and
  structures it in one pass, returning a LIST of segments per page (dense
  books run several cards per page; some put the card name on the previous
  page — a `continues` flag stitches across pages). Card guesses from the
  model are normalized through importer.classify_heading: the model
  proposes, our alias tables dispose. Per-page transcripts append to
  pages.jsonl BEFORE segmentation, so an interrupted import resumes via
  reextract without re-paying pages already transcribed.

Both lanes render pages/NNN.webp for the in-app reader, record LLM cost in
the ai_usage ledger (kind="book_import"), and write manifest.yaml LAST — its
presence is the "import completed" marker (a crashed import is invisible to
discovery and can be re-run or deleted).

Nothing is discarded: chunks.json holds the ENTIRE book (card-keyed where it
maps, topic-tagged elsewhere) so a future embeddings/learning-mode phase
indexes the existing corpus without re-import.
"""

import io
import json
import re
import time
from base64 import b64encode
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

import httpx
import yaml

from tarot import db, importer
from tarot import config as cfgfile
from tarot import interpret as interp

EXTRACTOR_VERSION = 3  # v3: lane A anchors sections on the PDF outline
# Vision transcripts are prompt-shaped, not extractor-shaped: cache them under
# their own version so lane-A improvements never re-bill vision books.
VISION_PROMPT_VERSION = 2
RENDER_SCALE = 2.0          # 144 dpi — legible for the reader AND the vision model
PAGE_QUALITY = 80
HEADING_SIZE_RATIO = 1.15   # lane A: a heading line is >= this x the body size
MIN_CARDS_FOR_HEURISTIC = 22

Progress = Callable[[str, int, int], None]  # (stage, done, total)


class BookImportError(Exception):
    """User-facing import failure (bad PDF, missing vision model, ...)."""


def vision_config() -> dict | None:
    """LLM config with the vision model swapped in (file > DB > main model)."""
    cfg = interp.config()
    if not cfg:
        return None
    model = (cfgfile.get("books", "vision_model")
             or db.get_setting("books_vision_model")
             or cfg.get("model"))
    return {**cfg, "model": model}


def _record(owner: str, cfg: dict, usage: dict | None, chars: int) -> None:
    usage = usage or {}
    try:
        db.record_usage(owner=owner, component="llm", kind="book_import",
                        model=cfg.get("model"),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        characters=chars, audio_bytes=None)
    except Exception:
        pass  # accounting must never break an import


def _chat(cfg: dict, messages: list[dict], owner: str, max_tokens: int = 4000) -> str:
    resp = httpx.post(
        f"{cfg['base_url']}/chat/completions",
        headers=interp._auth_headers(cfg),
        json={"model": cfg["model"], "messages": messages, "max_tokens": max_tokens},
        timeout=httpx.Timeout(180.0, connect=15.0),
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    _record(owner, cfg, data.get("usage"), len(text))
    return text


def _json_block(text: str) -> dict | list | None:
    """Parse the first JSON object/array in a model reply (tolerates fences)."""
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        return None
    for end in range(len(text), start, -1):
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
    return None


# --- rendering ---------------------------------------------------------------

def _render_pages(doc, pages_dir: Path, on_progress: Progress | None) -> int:
    import pypdfium2  # noqa: F401 — doc already comes from pdfium; kept for clarity

    pages_dir.mkdir(parents=True, exist_ok=True)
    n = len(doc)
    for i in range(n):
        out = pages_dir / f"{i:03d}.webp"
        if out.is_file():
            continue  # reextract: renders are deterministic, keep them
        page = doc[i]
        try:
            page.render(scale=RENDER_SCALE).to_pil().save(out, quality=PAGE_QUALITY)
        finally:
            page.close()
        if on_progress:
            on_progress("render", i + 1, n)
    return n


# --- lane A: text-layer PDFs --------------------------------------------------

def _page_lines(doc) -> list[list[tuple[float, str]]]:
    """Per page: [(max char height, line text), ...] in content order.

    Chars are clustered into lines by vertical MIDPOINT, walking the content
    stream sequentially — bucketing on the bottom edge would split any line
    containing a descender glyph (g/p/y sit lower than the baseline).
    """
    all_pages = []
    for i in range(len(doc)):
        page = doc[i]
        tp = page.get_textpage()
        lines: list[tuple[float, str]] = []
        cur_text, cur_mid, cur_hs = "", None, []
        def flush():
            nonlocal cur_text, cur_mid, cur_hs
            if cur_text.strip() and cur_hs:
                # median glyph height: robust against a lone tall glyph
                # ('j', parens) inflating a body line into a heading
                lines.append((sorted(cur_hs)[len(cur_hs) // 2], " ".join(cur_text.split())))
            cur_text, cur_mid, cur_hs = "", None, []
        for c in range(tp.count_chars()):
            ch = tp.get_text_range(c, 1)
            if ch in ("\r", "\n"):
                continue
            _, bottom, _, top = tp.get_charbox(c)
            h = top - bottom
            if ch.isspace() or h <= 0:
                cur_text += " "
                continue
            mid = (top + bottom) / 2
            if cur_mid is not None and abs(mid - cur_mid) <= 0.6 * max(h, *cur_hs):
                cur_text += ch
                cur_hs.append(h)
            else:
                flush()
                cur_text, cur_mid, cur_hs = ch, mid, [h]
        flush()
        tp.close()
        page.close()
        all_pages.append(lines)
    return all_pages


ORIENT_RE = re.compile(r"^\s*(upright|reversed?)\b[:\s]*", re.IGNORECASE)


def _toc_card_anchors(doc) -> dict[int, tuple[int, float, str, str]]:
    """{page: (card index, confidence, title, source)} from the PDF outline —
    the strongest section signal a real published book carries ("VII, The
    Chariot" -> dest page). Books with junk outlines (img001...) match
    nothing and contribute nothing."""
    anchors: dict[int, tuple[int, float, str, str]] = {}
    try:
        entries = list(doc.get_toc())
    except Exception:
        return anchors
    for e in entries:
        try:
            title = e.get_title()
            dest = e.get_dest()
            page = dest.get_index() if dest else None
            if page is None:
                # outlines built on GoTo ACTIONS (common in published PDFs)
                # have no direct dest — resolve through the raw API
                import pypdfium2.raw as pdfium_c
                action = pdfium_c.FPDFBookmark_GetAction(e.raw)
                if action:
                    raw_dest = pdfium_c.FPDFAction_GetDest(e.pdf.raw, action)
                    if raw_dest:
                        idx = pdfium_c.FPDFDest_GetDestPageIndex(e.pdf.raw, raw_dest)
                        page = idx if idx >= 0 else None
        except Exception:
            continue
        if page is None or not title:
            continue
        index, conf = importer.classify_heading(title)
        if index is not None and conf >= 0.8 and page not in anchors:
            anchors[page] = (index, conf, title, "toc")
    return anchors


# "The Chariot .... 132" | "Hanged Man, The, 78–81" | "The Fool 62-65":
# title, then the FIRST printed page of a number-or-range tail.
_CONTENTS_LINE = re.compile(r"^(.*?)(?:[\s.·]{2,}|,\s+)(\d{1,4})(?:\s*[–—-]\s*\d{1,4})?$")


def _contents_anchors(pages: list,
                      heading_pages: dict[int, int] | None = None
                      ) -> dict[int, tuple[int, float, str, str]]:
    """{pdf page: (card index, conf, title, "contents")} from a PRINTED
    contents page (front) or index (back). Printed page numbers aren't PDF
    indices: the offset is recovered from page folios (the modal difference
    between a page's printed number line — first or last line — and its PDF
    index). Per card the SMALLEST printed page wins (an index cites a card
    on many pages; the section starts at the first)."""
    from collections import Counter as _Counter

    edge = max(6, len(pages) // 8)  # contents up front, index at the back
    scan = list(pages[:edge]) + list(pages[-edge:])
    best: dict[int, tuple[int, str]] = {}  # card -> (printed page, title)
    for lines in scan:
        for _, text in lines:
            m = _CONTENTS_LINE.match(text.strip())
            if not m:
                continue
            title, num = m.group(1).strip(" ,"), int(m.group(2))
            index, conf = importer.classify_heading(title)
            if index is None or conf < 0.8:
                continue
            if index not in best or num < best[index][0]:
                best[index] = (num, title)
    if not best:
        return {}
    # printed page -> PDF index offset, from two independent signals:
    offsets: _Counter = _Counter()
    # (a) page folios (first/last line that is a bare number)
    for pno, lines in enumerate(pages):
        for _, text in (lines[:1] + lines[-1:]):
            t = text.strip()
            if t.isdigit() and len(t) <= 4:
                offsets[pno - int(t)] += 1
    # (b) calibration against confidently-detected section headings — covers
    # ebook-style PDFs with an index but no printed folios
    for index, (num, _) in best.items():
        if heading_pages and index in heading_pages:
            offsets[heading_pages[index] - num] += 1
    if not offsets:
        return {}
    offset, votes = offsets.most_common(1)[0]
    if votes < 5:  # no consistent mapping — printed numbers are unusable
        return {}
    anchors: dict[int, tuple[int, float, str, str]] = {}
    for index, (num, title) in best.items():
        page = num + offset
        if 0 <= page < len(pages) and page not in anchors:
            anchors[page] = (index, 0.9, title, "contents")
    return anchors


def _extract_text_lane(doc, owner: str, on_progress: Progress | None) -> tuple[list[dict], bool]:
    pages = _page_lines(doc)
    toc_anchors = _toc_card_anchors(doc)
    body = Counter(round(h) for lines in pages for h, _ in lines).most_common(1)[0][0]

    candidates = []  # {id, page, text, index, conf}
    for pno, lines in enumerate(pages):
        for h, text in lines:
            if h >= body * HEADING_SIZE_RATIO and len(text) <= 60:
                index, conf = importer.classify_heading(text)
                candidates.append({"id": len(candidates), "page": pno,
                                   "text": text, "index": index, "conf": conf})

    matched = {c["id"] for c in candidates if c["index"] is not None and c["conf"] >= 0.8}
    # index/contents anchors, calibrated by the confident line headings; the
    # PDF outline still wins where both name a page
    heading_pages = {}
    for c in candidates:
        if c["id"] in matched and c["conf"] >= 0.9:
            heading_pages.setdefault(c["index"], c["page"])
    for pg, v in _contents_anchors(pages, heading_pages).items():
        toc_anchors.setdefault(pg, v)
    llm_assisted = False
    if len({c["index"] for c in candidates if c["id"] in matched}) < MIN_CARDS_FOR_HEURISTIC:
        cfg = interp.config()
        if cfg:
            ambiguous = [c for c in candidates if c["id"] not in matched]
            if ambiguous:
                if on_progress:
                    on_progress("classify", 0, 1)
                prompt = (
                    "These are heading lines from a tarot guidebook PDF. For each id, "
                    "reply with the canonical card index 0-77 it introduces (majors 0-21 "
                    "in Rider-Waite order with 8=Strength 11=Justice, then wands 22-35, "
                    "cups 36-49, swords 50-63, pentacles 64-77 each ace..king) or null "
                    "if it is not a single card's heading. Reply with ONLY a JSON object "
                    "mapping id to index-or-null.\n\n"
                    + "\n".join(f'{c["id"]}: {c["text"]!r} (page {c["page"] + 1})'
                                for c in ambiguous)
                )
                for _ in range(2):
                    try:
                        reply = _chat(cfg, [{"role": "user", "content": prompt}], owner)
                    except httpx.HTTPError:
                        break
                    mapping = _json_block(reply)
                    if isinstance(mapping, dict):
                        for c in ambiguous:
                            v = mapping.get(str(c["id"]))
                            if isinstance(v, int) and 0 <= v <= 77:
                                c["index"], c["conf"] = v, 0.7
                                matched.add(c["id"])
                        llm_assisted = True
                        break

    # segment: walk lines, split at accepted headings
    heads = {(c["page"], c["text"]): c for c in candidates if c["id"] in matched}
    other_heads = {(c["page"], c["text"]) for c in candidates if c["id"] not in matched}
    chunks: list[dict] = []
    chapter = None
    current: dict | None = None
    for pno, lines in enumerate(pages):
        # Outline-anchored section start: authoritative even when the page's
        # heading line evades the font-size heuristics. Skipped when a line
        # on this page already matches the same card (the line will open it).
        if pno in toc_anchors:
            index, conf, title, src = toc_anchors[pno]
            line_opens_it = any(
                heads[k]["index"] == index for k in ((pno, t) for _, t in lines) if k in heads
            )
            if not line_opens_it:
                current = {"kind": "card", "chapter": chapter, "heading": title,
                           "card_index": index, "orientation": None,
                           "pages": [pno], "confidence": max(conf, 0.95),
                           "source": src, "text": ""}
                chunks.append(current)
        for h, text in lines:
            key = (pno, text)
            if key in heads:
                c = heads[key]
                current = {"kind": "card", "chapter": chapter, "heading": text,
                           "card_index": c["index"], "orientation": None,
                           "pages": [pno], "confidence": c["conf"],
                           "source": "llm" if c["conf"] == 0.7 else "heuristic",
                           "text": ""}
                chunks.append(current)
                continue
            m = ORIENT_RE.match(text)
            if m and current and current["kind"] == "card" and len(text) <= 40:
                # orientation sub-heading inside a card section — must be
                # checked BEFORE the generic-heading branch, which would
                # otherwise consume "Reversed" as an essay heading
                orient = "reversed" if m.group(1).lower().startswith("rev") else "upright"
                current = {**current, "orientation": orient, "pages": [pno], "text": ""}
                chunks.append(current)
                continue
            if key in other_heads:
                chapter = text
                current = {"kind": "essay", "chapter": chapter, "heading": text,
                           "card_index": None, "orientation": None,
                           "pages": [pno], "text": ""}
                chunks.append(current)
                continue
            if current is None:
                current = {"kind": "front", "chapter": None, "heading": None,
                           "card_index": None, "orientation": None,
                           "pages": [pno], "text": ""}
                chunks.append(current)
            current["text"] = (current["text"] + " " + text).strip()
            if pno not in current["pages"]:
                current["pages"].append(pno)
    # Anchor credit: a card chunk that STARTS on its outline/contents-anchored
    # page is the authoritative section even when the heading line (not the
    # anchor) opened it — stamp the source so ranking prefers it over longer
    # stray-mention chunks elsewhere in the book.
    anchor_pages = {v[0]: (pg, v[3]) for pg, v in toc_anchors.items()}
    for ch in chunks:
        ci = ch.get("card_index")
        if ci in anchor_pages and ch.get("pages") and min(ch["pages"]) == anchor_pages[ci][0]:
            ch["source"] = anchor_pages[ci][1]
            ch["confidence"] = max(ch.get("confidence", 0.0), 0.95)
    return chunks, llm_assisted


# --- lane B: image-only PDFs (vision) ----------------------------------------

VISION_SYSTEM = """You transcribe pages of tarot guidebooks from images, exactly and completely.
Reply with ONLY a JSON object: {"segments": [...]}. Each segment:
{"heading": str|null,        // the heading line as printed, if any
 "card": str|null,           // canonical tarot card this section is about, e.g. "The Tower" or "Two of Cups", null if not about a single card
 "orientation": "upright"|"reversed"|null,   // if the section is specifically one orientation
 "kind": "card"|"essay"|"front"|"toc",
 "chapter": str|null,        // running chapter/section banner if visible
 "continues": bool,          // true if the page STARTS mid-section (its first text continues the previous page's last segment)
 "sections": {"keywords": str, "love": str, "career": str, "finances": str}|null,  // only when the page labels such sub-sections
 "text": str}                // the full transcribed text of the segment, reading order
Rules: multi-column pages are read column by column. EVERYTHING belonging to
one card — its themed/story title, the story or description prose, and its
keyword lists — goes into that card's segment(s): put the prose in "text" and
labeled keyword lists in "sections" (e.g. {"upright": ..., "reversed": ...});
NEVER emit a card's prose block as a separate essay segment.
A page listing several cards inline ("FIVE OF SWORDS: ...") yields one segment per card.
Transcribe faithfully; do not summarize, translate, or invent text."""


def _transcribe_pages(dest: Path, n: int, owner: str,
                      on_progress: Progress | None) -> tuple[list[list[dict]], list[int]]:
    cfg = vision_config()
    if not cfg:
        raise BookImportError(
            "This PDF has no text layer (image-only) and no AI endpoint is "
            "configured to read it — configure the LLM (and books.vision_model).")
    cache_path = dest / "pages.jsonl"
    cached: dict[int, list[dict]] = {}
    if cache_path.is_file():
        for line in cache_path.read_text().splitlines():
            try:
                rec = json.loads(line)
                # transcripts are prompt-shaped: only reuse ones produced by
                # the current extractor version (a prompt change re-pays)
                if rec.get("v") == VISION_PROMPT_VERSION:
                    cached[rec["page"]] = rec["segments"]
            except (json.JSONDecodeError, KeyError):
                continue
    per_page: list[list[dict]] = []
    failed: list[int] = []
    with cache_path.open("a") as cache:
        for i in range(n):
            if i in cached:
                per_page.append(cached[i])
                continue
            img = (dest / "pages" / f"{i:03d}.webp").read_bytes()
            data_url = "data:image/webp;base64," + b64encode(img).decode()
            segments = None
            for _ in range(2):
                try:
                    reply = _chat(cfg, [
                        {"role": "system", "content": VISION_SYSTEM},
                        {"role": "user", "content": [
                            {"type": "text", "text": f"Page {i + 1} of a tarot guidebook."},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ]},
                    ], owner)
                except httpx.HTTPError as e:
                    if i == 0:  # first page failing = model can't do images: stop early
                        raise BookImportError(
                            f"vision transcription failed — is books.vision_model "
                            f"a vision-capable model? ({e})")
                    continue
                parsed = _json_block(reply)
                if isinstance(parsed, dict) and isinstance(parsed.get("segments"), list):
                    segments = parsed["segments"]
                    break
            if segments is None:
                failed.append(i)
                segments = []
            cache.write(json.dumps({"page": i, "v": VISION_PROMPT_VERSION, "segments": segments}) + "\n")
            cache.flush()
            per_page.append(segments)
            if on_progress:
                on_progress("transcribe", i + 1, n)
    return per_page, failed


def _stitch_vision(per_page: list[list[dict]]) -> tuple[list[dict], bool]:
    chunks: list[dict] = []
    chapter = None
    for pno, segments in enumerate(per_page):
        for si, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            text = " ".join(str(seg.get("text") or "").split())
            chapter = seg.get("chapter") or chapter
            if si == 0 and seg.get("continues") and chunks:
                prev = chunks[-1]
                prev["text"] = (prev["text"] + " " + text).strip()
                if pno not in prev["pages"]:
                    prev["pages"].append(pno)
                if seg.get("sections") and not prev.get("sections"):
                    prev["sections"] = seg["sections"]
                continue
            guess = seg.get("card") or seg.get("heading") or ""
            index, conf = importer.classify_heading(str(guess))
            if index is None:
                # models sometimes transcribe the card name as the first text
                # line but leave the card field null (stylized headings) —
                # split the RAW text (`text` is already newline-collapsed)
                first_line = str(seg.get("text") or "").split("\n", 1)[0].strip()
                if first_line:
                    index, conf = importer.classify_heading(first_line[:48])
            if index is None and str(guess).strip().isdigit():
                # a bare-number card guess ("13") = the page titles the card
                # by numeral alone (soft-deck convention for Death)
                n = int(str(guess).strip())
                if 0 <= n <= 21:
                    index, conf = n, 0.6
            kind = seg.get("kind") if seg.get("kind") in ("card", "essay", "front", "toc") else "essay"
            if index is None:
                kind = kind if kind != "card" else "essay"
            orientation = seg.get("orientation")
            chunks.append({
                "kind": "card" if index is not None else kind,
                "chapter": seg.get("chapter") or chapter,
                "heading": seg.get("heading"),
                "card_index": index,
                "orientation": orientation if orientation in ("upright", "reversed") else None,
                "pages": [pno],
                "confidence": conf,
                "source": "vision",
                "sections": seg.get("sections") if isinstance(seg.get("sections"), dict) else None,
                "text": text,
            })
    return chunks, True


# --- shared assembly ----------------------------------------------------------

def _slugify(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or None


_CARD_GROUPS = [(0, 22), (22, 36), (36, 50), (50, 64), (64, 78)]


def _flag_primaries(cards: dict[str, list[dict]]) -> None:
    """Mark each card's PRIMARY entry: guidebooks run majors and each suit in
    order, so among a card's candidate chunks prefer the one that best fits a
    non-decreasing page chain through its group — a stray mention elsewhere
    in the book (a spread example, an intro) loses to sequence fit even when
    its text is longer. Anchored entries (PDF outline / printed contents) are
    fixed points."""
    for lo, hi in _CARD_GROUPS:
        seq = []
        for ci in range(lo, hi):
            entries = [e for e in cards.get(str(ci), []) if e.get("pages")]
            if not entries:
                continue
            anchored = [e for e in entries if e.get("source") in ("toc", "contents")]
            pool = anchored or entries
            pages_ = sorted({min(e["pages"]) for e in pool})
            seq.append((ci, pages_, entries))
        if not seq:
            continue
        n = len(seq)
        dp = [[1] * len(c[1]) for c in seq]
        par = [[None] * len(c[1]) for c in seq]
        for a in range(n):
            for j, pj in enumerate(seq[a][1]):
                for b in range(a):
                    for k, pk in enumerate(seq[b][1]):
                        if pk <= pj and dp[b][k] + 1 > dp[a][j]:
                            dp[a][j], par[a][j] = dp[b][k] + 1, (b, k)
        end = max(((dp[a][j], a, j) for a in range(n) for j in range(len(seq[a][1]))))
        chain = {}
        cur = (end[1], end[2])
        while cur is not None:
            a, j = cur
            chain[a] = seq[a][1][j]
            cur = par[a][j]
        for pos, (ci, pages_, entries) in enumerate(seq):
            target = chain.get(pos)
            if target is None:
                prevp = max((chain[x] for x in chain if x < pos), default=None)
                nextp = min((chain[x] for x in chain if x > pos), default=None)
                ref = prevp if prevp is not None else nextp
                target = min(pages_, key=lambda pg: abs(pg - (ref if ref is not None else pg)))
            best = max((e for e in entries if min(e["pages"]) == target),
                       key=lambda e: len(e.get("text", "")), default=None)
            if best is not None:
                best["primary"] = True


def _assemble(dest: Path, name: str, owner: str, source: str, pages: int,
              chunks: list[dict], llm_assisted: bool, decks: list[str] | None) -> dict:
    for i, chunk in enumerate(chunks):
        chunk["id"] = i
        topics = [t for t in (_slugify(chunk.get("chapter")), _slugify(chunk.get("heading"))) if t]
        chunk["topics"] = list(dict.fromkeys(topics))
    cards: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        if chunk.get("card_index") is not None and chunk.get("text"):
            cards[str(chunk["card_index"])].append({
                "chunk": chunk["id"],
                "heading": chunk.get("heading"),
                "orientation": chunk.get("orientation"),
                "pages": chunk.get("pages", []),
                "confidence": chunk.get("confidence", 1.0),
                "source": chunk.get("source", "heuristic"),
                "sections": chunk.get("sections"),
                "text": chunk["text"],
            })
    _flag_primaries(cards)
    (dest / "chunks.json").write_text(json.dumps({"version": 1, "chunks": chunks}))
    (dest / "cards.json").write_text(json.dumps(dict(cards)))
    manifest = {
        "name": name,
        "source": source,
        "attribution": f"Uploaded by {owner}",
        "extractor": EXTRACTOR_VERSION,
        "llm_assisted": llm_assisted,
        "imported_at": int(time.time()),
        "pages": pages,
        "cards_covered": len(cards),
        "chunk_count": len(chunks),
    }
    if decks:
        manifest["decks"] = decks
    # manifest LAST: its presence is the "import completed" marker
    (dest / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))
    return {"pages": pages, "cards_covered": len(cards),
            "chunk_count": len(chunks), "llm_assisted": llm_assisted}


def import_book(pdf_path: Path, dest: Path, owner: str, name: str,
                on_progress: Progress | None = None,
                decks: list[str] | None = None) -> dict:
    """Run the full import into `dest` (the book's folder, source.pdf already
    there). Returns {pages, cards_covered, chunk_count, llm_assisted, failed_pages?}.
    Raises BookImportError with a user-facing message on unusable input."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(str(pdf_path))
    except Exception:
        raise BookImportError("not a readable PDF")
    try:
        n = _render_pages(doc, dest / "pages", on_progress)
        if n == 0:
            raise BookImportError("PDF has no pages")
        # Lane selection: sample a bounded prefix and compare against the
        # SAMPLED page count — scaling the threshold by total pages while
        # capping the sample misroutes every long text book to vision.
        sample = min(n, 20)
        total_chars = 0
        for i in range(sample):
            page = doc[i]
            tp = page.get_textpage()
            total_chars += tp.count_chars()
            tp.close()
            page.close()
        if total_chars >= 40 * sample:  # real text layer
            chunks, llm_assisted = _extract_text_lane(doc, owner, on_progress)
            failed: list[int] = []
        else:
            per_page, failed = _transcribe_pages(dest, n, owner, on_progress)
            chunks, llm_assisted = _stitch_vision(per_page)
    finally:
        doc.close()
    result = _assemble(dest, name, owner, "upload", n, chunks, llm_assisted, decks)
    if failed:
        result["failed_pages"] = failed
    return result


if __name__ == "__main__":  # dev harness: tune heuristics against real PDFs
    import argparse, tempfile

    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", help="book folder (default: temp dir)")
    args = ap.parse_args()
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="bookimport-"))
    out.mkdir(parents=True, exist_ok=True)

    def progress(stage, done, total):
        print(f"\r{stage} {done}/{total}", end="", flush=True)

    res = import_book(Path(args.pdf), out, "dev", Path(args.pdf).stem, progress)
    print(f"\n{res}\nwrote {out}")
