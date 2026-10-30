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
CAP_TAB = re.compile(r"^\s*(?:TABLE|Tab\.?)\s*([IVXLC]+|\d+)\s*[:.]\s*(.*)$")
H1 = re.compile(r"^([IVXLC]+)\.\s+([A-Za-z][A-Za-z \-]+)$")
H2 = re.compile(r"^([A-Z])\.\s+([A-Z][a-z].*)$")
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
    left = sum(1 for b in blocks if (b[0] + b[2]) / 2 < W / 2)
    right = len(blocks) - left
    return left >= 3 and right >= 3


def col_of(rect, page):
    """Return 'L' or 'R' for a rect, or '' for a single-column page."""
    if not two_column(page):
        return ""
    return "L" if (rect[0] + rect[2]) / 2 < page.rect.width / 2 else "R"


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
            keep = bool(m) and (m.group(1).isupper() or
                                bool(re.search(r"\d", m.group(1))) or
                                m.group(1).lower() in STOP_HYPHEN or
                                (m.group(1).lower() in wordset and len(m.group(1)) >= 4))
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
    """Per page: list of (label, caption, clip_rect) for figure captions."""
    out = {}
    for pno, page in enumerate(doc):
        prev = {"": 30.0, "L": 30.0, "R": 30.0}
        caps = []
        for blk in page.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for ln in blk["lines"]:
                t = "".join(s["text"] for s in ln["spans"]).strip()
                m = CAP_FIG.match(t)
                if m:
                    caps.append((m.group(1), m.group(2).strip(), ln["bbox"]))
        caps.sort(key=lambda c: c[2][1])
        res = []
        for label, cap, bb in caps:
            y0 = bb[1]
            side = col_of(bb, page)
            x0, x1 = band(page, side)
            ytop = prev[side]
            boxes = []
            for d in page.get_drawings():
                r = pymupdf.Rect(d["rect"])
                if ytop <= r.y1 <= y0 + 2 and r.x1 > x0 and r.x0 < x1 and r.get_area() > 1:
                    boxes.append(r)
            for im in page.get_image_info():
                r = pymupdf.Rect(im["bbox"])
                if ytop <= r.y1 <= y0 + 2 and r.x1 > x0 and r.x0 < x1:
                    boxes.append(r)
            clip = pymupdf.Rect(x0, ytop, x1, y0 - 2)
            if boxes:
                u = boxes[0]
                for b in boxes[1:]:
                    u |= b
                u = pymupdf.Rect(max(u.x0, x0), max(u.y0, ytop),
                                 min(u.x1, x1), min(u.y1, y0 - 2))
                if u.width > 20 and u.height > 12:
                    clip = u + (-3, -3, 3, 3)
            prev[side] = bb[3]
            res.append((label, cap, clip))
        out[pno] = res
    return out


def fig_filename(label):
    return "fig" + label.replace(".", "-") + ".png"


# --------------------------------------------------------------------------- #
# tables
# --------------------------------------------------------------------------- #
def table_captions(page):
    caps = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            t = "".join(s["text"] for s in ln["spans"]).strip()
            m = CAP_TAB.match(t)
            if m:
                caps.append((m.group(1), m.group(2).strip(), ln["bbox"]))
    return caps


def find_tables(page):
    """Keep only detected tables having a TABLE caption just below (same column
    when the page is two-column). Returns (label, caption, bbox, rows)."""
    caps = table_captions(page)
    found = []
    for t in page.find_tables().tables:
        bb = pymupdf.Rect(t.bbox)
        for label, cap, cbb in caps:
            # a caption sits directly under its table; the column test is
            # unreliable because full-width captions centre on the page midline.
            if 0 <= cbb[1] - bb.y1 <= 80:
                rows = [[re.sub(r"\s+", " ", c or "").strip() for c in row]
                        for row in t.extract()]
                found.append((label, cap, bb, rows))
                break
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
        m2 = H2.match(f)
        if m2:
            heads.append(f"### {m2.group(1)}. {m2.group(2)}")
            lines = lines[1:]
            continue
        break
    return heads, lines


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

    doc = pymupdf.open(args.pdf)
    wordset = build_wordset(doc)
    clips = figure_clips(doc)
    os.makedirs(os.path.join(args.outdir, "pics"), exist_ok=True)
    md, manifest = [], []

    # ---- page-1 header ---------------------------------------------------- #
    top, abs_y = header_blocks(doc[0])
    md.extend(header_markdown(top))
    skip_extra = [tuple(b[:4]) for b in top]

    def is_header_block(b):
        return any(abs(b[0] - s[0]) < 1 and abs(b[1] - s[1]) < 1 and
                   abs(b[2] - s[2]) < 1 for s in skip_extra)

    for pno, page in enumerate(doc):
        W = page.rect.width
        mid = W / 2
        figclips = [c for _, _, c in clips.get(pno, [])]
        tables = find_tables(page)
        tableclips = [bb for _, _, bb, _ in tables]

        for label, cap, clip in clips.get(pno, []):
            pix = page.get_pixmap(dpi=args.dpi, clip=clip)
            fn = fig_filename(label)
            pix.save(os.path.join(args.outdir, "pics", fn))
            manifest.append({"label": label, "file": fn, "page": pno + 1,
                             "caption": cap, "clip": [round(v, 1) for v in clip]})

        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        blocks = [b for b in blocks if not SKIP.search(b[4])]
        if two_column(page):
            blocks.sort(key=lambda b: (col_of(b, page) == "R", b[1]))
        else:
            blocks.sort(key=lambda b: b[1])

        refmode, refbuf = False, []
        for b in blocks:
            text = b[4].strip()
            if not text or is_header_block(b):
                continue
            if any(inside(b, c) for c in figclips):
                continue
            if any(inside(b, c) for c in tableclips):
                continue
            lines = [l for l in text.split("\n") if l.strip()]
            first = lines[0].strip()

            if refmode:
                refbuf.append(text)
                continue
            if re.fullmatch(r"(REFERENCES|References)", first):
                md.append("## References\n")
                refmode = True
                continue

            mfig = CAP_FIG.match(first)
            if mfig:
                label, cap = mfig.group(1), mfig.group(2).strip()
                fn = fig_filename(label)
                md.append(f"![Fig. {label}: {cap}](pics/{fn})\n")
                md.append(f"*Fig. {label}: {cap}*\n")
                continue

            mtab = CAP_TAB.match(first)
            if mtab:
                key = mtab.group(1)
                rows, cap = None, " ".join(l.strip() for l in lines)
                for lbl, c, bb, r in tables:
                    if lbl == key:
                        rows, cap = r, c
                        break
                if rows:
                    md.append(markdown_table(rows) + "\n")
                md.append(f"*Table {key}: {cap}*\n")
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

        if refbuf:
            joined = " ".join(re.sub(r"\s*\n\s*", " ", t) for t in refbuf)
            for p in re.split(r"(?=\[\d+\]\s)", joined):
                p = p.strip()
                if p:
                    md.append(p + "\n")

    out_md = os.path.join(args.outdir, args.name + ".md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    json.dump(manifest, open(os.path.join(args.outdir, "figures.json"), "w"),
              indent=2, ensure_ascii=False)
    print(f"wrote {out_md}  ({len(manifest)} figures)")


if __name__ == "__main__":
    main()
