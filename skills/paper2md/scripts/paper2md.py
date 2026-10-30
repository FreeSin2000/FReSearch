#!/usr/bin/env python3
"""
FReSearch paper2md: two-column (IEEE/ACM-style) paper PDF -> Markdown.

Design goals
------------
* No OCR, no deep learning. Uses PyMuPDF only (plus optional pypdf fallback).
* Preserve real paragraphs. The sibling `pdf-chapter-translate` skill reads text
  with pypdf, which loses paragraph boundaries and mangles small-caps headings
  ("INTRODUCTION" -> "I NTRODUCTION"). For journal papers we instead read
  PyMuPDF *blocks* (one block ~= one paragraph) and order them by column.
* Vector figures. Papers rarely embed figures as bitmaps; the sibling skill's
  image-bbox crop therefore yields nothing. We crop the union of vector
  drawings in the caption's column, above the caption.
* Tables. `page.find_tables()` gives structured cells; we keep only tables that
  have a "TABLE n:" caption just below them (this filters the many false
  positives that table detection finds inside chart axes).

The output is for reading / translation, not print fidelity.

Usage
-----
    paper2md.py PAPER.pdf -o OUTDIR [--dpi 200] [--name paper]

    OUTDIR is normally papers/<slug>/md; figures go to OUTDIR/pics.

Outputs
-------
    OUTDIR/paper.md          the Markdown
    OUTDIR/pics/figNN.png    one image per figure
    OUTDIR/figures.json      manifest (label, caption, page, clip, file)
"""
import argparse
import json
import os
import re
import sys

import pymupdf

CAP_FIG = re.compile(r"^\s*(?:fig(?:ure)?)\.?\s*(\d+(?:\.\d+)?)\s*[:.]\s*(.*)$", re.I)
CAP_TAB = re.compile(r"^\s*(?:table|tab\.)\s*([IVXLC]+|\d+)\s*[:.]\s*(.*)$", re.I)
H1 = re.compile(r"^([IVXLC]+)\.\s+([A-Za-z][A-Za-z \-]+)$")
H2 = re.compile(r"^([A-Z])\.\s+([A-Z][a-z].*)$")
HNUM = re.compile(r"^(\d+(?:\.\d+)*)\s+([A-Za-z][^\n]*)$")
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SKIP = re.compile(
    r"Authorized licensed use|^\s*IEEE\b.*DOI:|10\.1109/|"
    r"Downloaded on .* from IEEE Xplore|Restrictions apply", re.I)

# Small stop-list of short prefixes that are real hyphens, not soft hyphenation.
STOP_HYPHEN = {"non", "pre", "post", "co", "re", "one", "two", "three", "multi",
               "self", "cross", "side", "state", "valley", "prefix", "destination",
               "neighbor", "high", "low", "p2c", "p2p", "s"}

# Set by --single-column: force one-column treatment even if the heuristic
# thinks the page is two-column (and vice versa is left to auto-detection).
FORCE_SINGLE_COLUMN = False


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def two_column(page):
    """Heuristic: does this page use two balanced text columns?

    Forced to False by --single-column. (Vice versa is not forced: a false
    positive is the dangerous case, so an explicit override in one direction
    is enough.)
    """
    if FORCE_SINGLE_COLUMN:
        return False
    W = page.rect.width
    blocks = [b for b in page.get_text("blocks")
              if b[6] == 0 and (b[2] - b[0]) > 20]
    # Column-width blocks only: a single-column body block is ~0.8 W wide and
    # starts at the left margin, so it must not count as a right-column block.
    narrow = [b for b in blocks if (b[2] - b[0]) < 0.45 * W]
    left = sum(1 for b in narrow if b[0] < 0.45 * W)
    right = sum(1 for b in narrow if b[0] >= 0.5 * W)
    return left >= 2 and right >= 1


def col_of(rect, page):
    """Return 'L' or 'R' for a rect, or '' for a single-column page."""
    if not two_column(page):
        return ""
    return "L" if (rect[0] + rect[2]) / 2 < page.rect.width / 2 else "R"


def sanitize(s):
    """Drop control bytes that PDF math glyphs leave behind (\x00, \x01...)."""
    return CTRL.sub("", s)


def page_blocks(page):
    """Text blocks with logically merged lines.

    Some templates emit a heading as two lines at the same y ("3" + "Semantics
    Aware Analysis"); merge same-y lines inside a block so heading and caption
    regexes see one string.
    """
    out = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        merged = []
        for ln in blk["lines"]:
            t = sanitize("".join(s["text"] for s in ln["spans"])).strip()
            if not t:
                continue
            b = pymupdf.Rect(ln["bbox"])
            if merged and abs(b.y0 - merged[-1]["bbox"].y0) <= 2:
                m = merged[-1]
                gap = b.x0 - m["bbox"].x1
                m["text"] = (m["text"] + ("  " if gap > 8 else " ") + t).strip()
                m["bbox"] |= b
            else:
                merged.append({"text": t, "bbox": b})
        if merged:
            out.append({"bbox": pymupdf.Rect(blk["bbox"]), "lines": merged,
                        "text": "\n".join(m["text"] for m in merged)})
    return out


def keep_hyphen(fragment, wordset):
    """True when a trailing '-' is a real compound hyphen, not a soft break."""
    return (fragment.isupper() or bool(re.search(r"\d", fragment))
            or fragment.lower() in STOP_HYPHEN
            or (fragment.lower() in wordset and len(fragment) >= 4))


def band(page, side, xmid=None):
    """x-range of a column (or whole text width if side == '')."""
    W = page.rect.width
    if side == "":
        return 36.0, W - 36.0
    if side == "L":
        return 36.0, W / 2 - 6
    return W / 2 + 6, W - 30


# --------------------------------------------------------------------------- #
# hyphenation
# --------------------------------------------------------------------------- #
def build_wordset(doc):
    words = set()
    for page in doc:
        # normalize line-break hyphens first, or "evolu-\ntion" pollutes the
        # word list with the fragment "evolu".
        t = re.sub(r"-\s*\n\s*", "", page.get_text())
        for w in re.findall(r"[A-Za-z]{4,}", t):
            words.add(w.lower())
    return words


def dehyphen_join(lines, wordset):
    """Join wrapped lines; remove soft hyphens but keep real compound hyphens.

    A trailing '-' is treated as a *soft* (line-break) hyphen and removed only
    when the fragment before it is not a plausible standalone word. We use the
    document's own vocabulary plus a small prefix stop-list.
    """
    out = ""
    for raw in lines:
        l = raw.strip()
        if not l:
            continue
        if out.endswith("-") and l[:1].islower():
            m = re.match(r".*?([A-Za-z0-9]+)-$", out)
            keep = bool(m) and keep_hyphen(m.group(1), wordset)
            out = (out + l) if keep else (out[:-1] + l)
        elif out:
            out += " " + l
        else:
            out = l
    return out


# --------------------------------------------------------------------------- #
# figures
# --------------------------------------------------------------------------- #
def figure_clips(doc):
    """Per page: list of (label, caption, clip_rect) for figure captions.

    Captions are matched on merged lines; the rest of the caption's block is
    appended, so multi-line captions are not truncated. A caption spanning both
    columns means a full-width figure: crop the full text width above it.
    """
    out = {}
    for pno, page in enumerate(doc):
        prev = {"": 30.0, "L": 30.0, "R": 30.0}
        caps = []
        for blk in page_blocks(page):
            lines = blk["lines"]
            for i, ln in enumerate(lines):
                m = CAP_FIG.match(ln["text"])
                if m:
                    cap = " ".join([m.group(2)] + [x["text"] for x in lines[i + 1:]])
                    caps.append((m.group(1), re.sub(r"\s+", " ", cap).strip(), ln["bbox"]))
                    break
        caps.sort(key=lambda c: c[2][1])
        res = []
        for label, cap, bb in caps:
            y0 = bb[1]
            full = (bb[2] - bb[0]) > 0.55 * page.rect.width
            side = "" if full else col_of(bb, page)
            x0, x1 = band(page, side)
            ytop = max(prev.values()) if full else prev[side]
            for _, _, cbb in table_captions(page):
                if cbb[3] < y0 and cbb[0] < x1 and cbb[2] > x0:
                    rb = rule_bottom(page, cbb, side, y0)
                    if rb:
                        ytop = max(ytop, rb + 3)
            draws = [pymupdf.Rect(d["rect"]) for d in page.get_drawings()
                     if ytop <= pymupdf.Rect(d["rect"]).y1 <= y0 + 2
                     and pymupdf.Rect(d["rect"]).x1 > x0
                     and pymupdf.Rect(d["rect"]).x0 < x1
                     and pymupdf.Rect(d["rect"]).get_area() > 1]
            imgs = [pymupdf.Rect(im["bbox"]) for im in page.get_image_info()
                    if ytop <= pymupdf.Rect(im["bbox"]).y1 <= y0 + 2
                    and pymupdf.Rect(im["bbox"]).x1 > x0
                    and pymupdf.Rect(im["bbox"]).x0 < x1]
            if imgs:
                # Bitmap panels define the figure area; nearby vector overlays
                # (arrows, frames) are kept, distant ones (a table above) are not.
                base = imgs[0]
                for r in imgs[1:]:
                    base |= r
                near = base + (-20, -20, 20, 20)
                boxes = imgs + [r for r in draws if r.intersects(near)]
            else:
                boxes = densest_cluster(draws)
            clip = pymupdf.Rect(x0, ytop, x1, y0 - 2)
            if boxes:
                u = boxes[0]
                for b in boxes[1:]:
                    u |= b
                u = pymupdf.Rect(max(u.x0, x0), max(u.y0, ytop),
                                 min(u.x1, x1), min(u.y1, y0 - 2))
                if u.width > 20 and u.height > 12:
                    clip = u + (-3, -3, 3, 3)
            if full:
                prev["L"] = prev["R"] = prev[""] = bb[3]
            else:
                prev[side] = bb[3]
            res.append((label, cap, clip))
        out[pno] = res
    return out


def rule_bottom(page, cbb, side, y0):
    """Bottom of a table whose horizontal rules start at the column margin."""
    W = page.rect.width
    left = 36.0 if side in ("", "L") else W / 2 + 6
    right = W - 30 if side in ("", "R") else W / 2 - 6
    bottom = None
    for d in page.get_drawings():
        r = pymupdf.Rect(d["rect"])
        if r.height <= 2 and r.width > 0.5 * (right - left):
            if r.x0 <= left + 20 and cbb[3] < r.y1 < y0:
                bottom = r.y1 if bottom is None else max(bottom, r.y1)
    return bottom


def densest_cluster(rects, gap=15.0):
    """Pick the drawing cluster with the largest area (skips a table above)."""
    if not rects:
        return []
    rects = sorted(rects, key=lambda r: r.y0)
    clusters, cur = [], [rects[0]]
    for r in rects[1:]:
        if r.y0 - max(x.y1 for x in cur) > gap:
            clusters.append(cur)
            cur = [r]
        else:
            cur.append(r)
    clusters.append(cur)

    def area(c):
        u = c[0]
        for r in c[1:]:
            u |= r
        return u.width * u.height

    return max(clusters, key=area)


def fig_filename(label):
    return "fig" + label.replace(".", "-") + ".png"


# --------------------------------------------------------------------------- #
# tables
# --------------------------------------------------------------------------- #
def table_captions(page):
    """All table captions on the page, with the rest of the caption block joined."""
    caps = []
    for blk in page_blocks(page):
        lines = blk["lines"]
        for i, ln in enumerate(lines):
            m = CAP_TAB.match(ln["text"])
            if m:
                cap = " ".join([m.group(2)] + [x["text"] for x in lines[i + 1:]])
                caps.append((m.group(1), re.sub(r"\s+", " ", cap).strip(), ln["bbox"]))
                break
    return caps


def rows_plausible(rows):
    """Reject detections that actually captured a plot or prose."""
    if not rows:
        return False
    counts = [sum(1 for c in row if c) for row in rows]
    thin = sum(1 for n in counts if n < 2)
    return thin / len(rows) <= 0.2


def find_tables(page):
    """Pair detected tables with captions above OR below (ACM puts them above).

    Returns (label, full_caption, bbox, rows).
    """
    caps = table_captions(page)
    found = []
    matched = set()
    for t in page.find_tables().tables:
        bb = pymupdf.Rect(t.bbox)
        best = None
        for label, cap, cbb in caps:
            for dist in (cbb[1] - bb.y1, bb.y0 - cbb[3]):
                if 0 <= dist <= 80 and (best is None or dist < best[0]):
                    best = (dist, label, cap)
        if best:
            rows = [[re.sub(r"\s+", " ", c or "").strip() for c in row]
                    for row in t.extract()]
            if not rows_plausible(rows):
                rows = None
            found.append((best[1], best[2], bb, rows))
            matched.add(best[1])
    for label, cap, cbb in caps:
        if label in matched:
            continue
        fb = fallback_table(page, cbb)
        if fb:
            found.append((label, cap, fb[0], fb[1]))
    return found


def markdown_table(rows):
    if not rows:
        return ""
    header = rows[0]
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join(["---"] * len(header)) + " |"]
    for r in rows[1:]:
        r = (r + [""] * len(header))[:len(header)]
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# headings / title
# --------------------------------------------------------------------------- #
def titlecase(s):
    small = {"And", "Of", "The", "For", "To", "A", "An", "In", "On", "With", "Via"}
    words = s.title().split()
    return " ".join(w.lower() if (i > 0 and w in small) else w
                    for i, w in enumerate(words))


def numeric_heading(f):
    """ACM-style numbered heading: '1 Introduction', '3.1 BEAM Overview'."""
    m = HNUM.match(f)
    if not m:
        return None
    num, title = m.group(1), m.group(2).strip()
    if num.count(".") > 2 or re.fullmatch(r"(19|20)\d\d", num):
        return None
    if len(title) > 80 or len(title.split()) > 12:
        return None
    if title[-1] in ".,;:-" or not title[0].isupper():
        return None
    return num, title


def peel_headings(lines):
    """Consume leading heading lines from a block (headings are sometimes merged
    with the following paragraph in one block, e.g. 'V. EVALUATION A. Overview')."""
    heads = []
    while lines:
        f = lines[0].strip()
        m1 = H1.match(f)
        if m1 and re.fullmatch(r"[A-Z][A-Z \-]*", m1.group(2)):
            heads.append(f"## {m1.group(1)}. {titlecase(m1.group(2))}")
            lines = lines[1:]
            continue
        mn = numeric_heading(f)
        if mn:
            level = "##" if "." not in mn[0] else "###"
            heads.append(f"{level} {mn[0]} {mn[1]}")
            lines = lines[1:]
            continue
        m2 = H2.match(f)
        if m2:
            heads.append(f"### {m2.group(1)}. {m2.group(2)}")
            lines = lines[1:]
            continue
        ml = re.match(r"^([A-Z])\s{2,}([A-Z][a-z][^\n]*)$", f)
        if ml and len(ml.group(2)) <= 80 and len(ml.group(2).split()) <= 12 \
                and ml.group(2)[-1] not in ".,;:-":
            heads.append(f"## {ml.group(1)} {ml.group(2)}")
            lines = lines[1:]
            continue
        break
    return heads, lines


def label_near(label, bbox, clips):
    """Guard against body text starting with 'Fig. N.' being read as a caption."""
    for lbl, _, clip in clips:
        if lbl == label and 0 <= bbox.y0 - clip.y1 <= 80:
            return True
    return False


def soft_hyphen_text(text, wordset):
    """Join 'prac- tical' inside a paragraph/reference string."""
    def repl(m):
        pre, post = m.group(1), m.group(2)
        return pre + ("-" if keep_hyphen(pre, wordset) else "") + post
    return re.sub(r"([A-Za-z0-9]+)-\s+([a-z])", repl, text)


def fix_cross_block_hyphens(text, wordset):
    """Join a paragraph ending in '-' with the next one starting lowercase."""
    parts = re.split(r"\n\s*\n", text)
    out = []
    i = 0
    while i < len(parts):
        cur = parts[i].rstrip()
        while i + 1 < len(parts):
            nxt = parts[i + 1].lstrip()
            if not (cur.endswith("-") and nxt[:1].islower()):
                break
            if cur.startswith(("#", "!", "|", "*", ">")) or nxt.startswith(("#", "!", "|", "*", ">")):
                break
            m = re.search(r"([A-Za-z0-9]+)-$", cur)
            if not m:
                break
            pre = m.group(1)
            cur = cur[:-1] + ("-" if keep_hyphen(pre, wordset) else "") + nxt
            i += 1
        out.append(cur)
        i += 1
    return "\n\n".join(out)


AFFIL = re.compile(r"Laborator|Universit|Institut|Department|School|College", re.I)


def header_blocks(page):
    """Top-of-page title / author / affiliation blocks (above the abstract)."""
    blocks = [b for b in page.get_text("blocks") if b[6] == 0]
    abs_y = None
    for b in blocks:
        if re.match(r"^\s*abstract\b", b[4].strip(), re.I):
            abs_y = b[1]
            break
    if abs_y is None:
        return [], None
    # header blocks are short and sit above the abstract; a right-column
    # paragraph can start a hair above the abstract line, so filter by height.
    top = [b for b in blocks if b[1] < abs_y and (b[3] - b[1]) < 45]
    top.sort(key=lambda b: (b[1], b[0]))
    return top, abs_y


def header_markdown(top):
    """Render title (incl. wrapped subtitle lines), authors and affiliation."""
    if not top:
        return []
    parts = [top[0][4].strip()]
    i = 1
    while i < len(top):
        t = top[i][4].strip()
        if "," not in t and not AFFIL.search(t) and len(t) < 100:
            parts.append(t)
            i += 1
        else:
            break
    out = ["# " + " ".join(parts) + "\n"]
    for b in top[i:]:
        t = " ".join(x.strip() for x in b[4].split("\n") if x.strip())
        out.append("*" + t + "*\n")
    return out


def flush_refs(md, refbuf, wordset):
    if not refbuf:
        return
    joined = " ".join(re.sub(r"\s*\n\s*", " ", t) for t in refbuf)
    joined = soft_hyphen_text(joined, wordset)
    for p in re.split(r"(?=\[\d+\]\s)", joined):
        p = p.strip()
        if p:
            md.append(p + "\n")
    refbuf.clear()


def fallback_table(page, cbb):
    """Last resort for tables without ruling lines (ACM merged headers).

    Uses text-based detection on the region below the caption. Returns
    (bbox, rows_or_None); rows=None means "mask it but do not emit a table".
    """
    x0, x1 = band(page, "")
    region = pymupdf.Rect(max(cbb[0], x0) - 2, cbb[3] + 2,
                          min(cbb[2], x1) + 2, cbb[3] + 260)
    try:
        tabs = page.find_tables(clip=region, strategy="text").tables
    except Exception:  # noqa: BLE001 - detection is best-effort
        return None
    if not tabs:
        return None
    t = max(tabs, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
    bb = pymupdf.Rect(t.bbox)
    if bb.y0 - cbb[3] > 40:
        return None
    # Text-based detection on merged-header tables is too unreliable to emit:
    # use its bbox only, to mask the region and emit a caption + placeholder.
    return (bb, None)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def inside(rect, clip):
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    return clip.x0 <= cx <= clip.x1 and clip.y0 <= cy <= clip.y1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("-o", "--outdir", required=True)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--name", default="paper", help="output basename (default paper)")
    ap.add_argument("--single-column", action="store_true",
                    help="force single-column handling: order text by y only and "
                         "crop figures full-width (for papers the 2-column "
                         "heuristic misclassifies)")
    args = ap.parse_args()

    global FORCE_SINGLE_COLUMN
    FORCE_SINGLE_COLUMN = args.single_column

    if not os.path.isfile(args.pdf):
        ap.error(f"no such file: {args.pdf}")
    try:
        doc = pymupdf.open(args.pdf)
    except Exception as exc:  # noqa: BLE001 - surface a clean message
        sys.exit(f"error: cannot open {args.pdf}: {exc}")

    wordset = build_wordset(doc)
    clips = figure_clips(doc)
    os.makedirs(os.path.join(args.outdir, "pics"), exist_ok=True)
    md, manifest = [], []

    # ---- page-1 header ---------------------------------------------------- #
    top, abs_y = header_blocks(doc[0])
    md.extend(header_markdown(top))
    skip_extra = [tuple(b[:4]) for b in top]

    def is_header_block(b):
        bb = b["bbox"]
        return any(abs(bb[0] - s[0]) < 1 and abs(bb[1] - s[1]) < 1 and
                   abs(bb[2] - s[2]) < 1 for s in skip_extra)

    # Document-level: references continue across pages, so this must not reset.
    refmode, refbuf = False, []

    for pno, page in enumerate(doc):
        figclips = [c for _, _, c in clips.get(pno, [])]
        figcap = {label: cap for label, cap, _ in clips.get(pno, [])}
        tabcap = {label: cap for label, cap, _ in table_captions(page)}
        tables = find_tables(page)
        tableclips = [bb for _, _, bb, _ in tables]

        for label, cap, clip in clips.get(pno, []):
            pix = page.get_pixmap(dpi=args.dpi, clip=clip)
            fn = fig_filename(label)
            pix.save(os.path.join(args.outdir, "pics", fn))
            manifest.append({"label": label, "file": fn, "page": pno + 1,
                             "caption": cap, "clip": [round(v, 1) for v in clip]})

        blocks = [b for b in page_blocks(page) if not SKIP.search(b["text"])]
        if two_column(page):
            blocks.sort(key=lambda b: (col_of(b["bbox"], page) == "R", b["bbox"][1]))
        else:
            blocks.sort(key=lambda b: b["bbox"][1])

        for b in blocks:
            text = b["text"].strip()
            if not text or is_header_block(b):
                continue
            lines = [l["text"] for l in b["lines"]]
            first = lines[0].strip()
            is_tabcap = bool(CAP_TAB.match(first))
            if not is_tabcap and any(inside(b["bbox"], c) for c in figclips):
                continue
            if not is_tabcap and any(inside(b["bbox"], c) for c in tableclips):
                continue

            if refmode:
                if re.match(r"^(?:Appendix\b|[A-Z]\s{2,}[A-Z][a-z])", first):
                    flush_refs(md, refbuf, wordset)
                    refmode = False
                else:
                    refbuf.append(text)
                    continue
            if re.fullmatch(r"(REFERENCES|References)", first):
                md.append("## References\n")
                refmode = True
                continue

            mfig = CAP_FIG.match(first)
            if mfig and label_near(mfig.group(1), b["bbox"], clips.get(pno, [])):
                label = mfig.group(1)
                cap = soft_hyphen_text(figcap.get(label) or mfig.group(2).strip(), wordset)
                fn = fig_filename(label)
                md.append(f"![Fig. {label}: {cap}](pics/{fn})\n")
                md.append(f"*Fig. {label}: {cap}*\n")
                continue

            mtab = CAP_TAB.match(first)
            if mtab:
                key = mtab.group(1)
                cap = soft_hyphen_text(tabcap.get(key, mtab.group(2).strip()), wordset)
                rows, found = None, False
                for lbl, c, bb, r in tables:
                    if lbl == key:
                        rows, cap, found = r, c, True
                        break
                if rows:
                    md.append(markdown_table(rows) + "\n")
                md.append(f"*Table {key}: {cap}*\n")
                if not found:
                    md.append(f"> Table {key} could not be extracted (see PDF p. {pno + 1}).\n")
                elif rows is None:
                    md.append(f"> Table {key} detected but too complex to extract; "
                              f"see PDF p. {pno + 1}.\n")
                continue

            if re.fullmatch(r"abstract", first, re.I):
                md.append("## Abstract\n")
                body = dehyphen_join(lines[1:], wordset)
                if body:
                    md.append(body + "\n")
                continue

            heads, rest = peel_headings(lines)
            if heads:
                md.extend(h + "\n" for h in heads)
                if not rest:
                    continue
                lines = rest
                first = lines[0].strip()

            if re.match(r"^\s*Abstract[—\-:]", first):
                body = re.sub(r"^\s*Abstract[—\-:]\s*", "", first)
                body = dehyphen_join([body] + lines[1:], wordset)
                md.append("## Abstract\n")
                md.append(body + "\n")
                continue

            body = dehyphen_join(lines, wordset)
            body = re.sub(r"^#", r"\\#", body)   # '#hits / #d2a' is not a heading
            md.append(body + "\n")

        flush_refs(md, refbuf, wordset)

    out_text = sanitize("\n".join(md))
    out_text = fix_cross_block_hyphens(out_text, wordset)
    out_md = os.path.join(args.outdir, args.name + ".md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(out_text)
    json.dump(manifest, open(os.path.join(args.outdir, "figures.json"), "w"),
              indent=2, ensure_ascii=False)
    print(f"wrote {out_md}  ({len(manifest)} figures)")


if __name__ == "__main__":
    main()
