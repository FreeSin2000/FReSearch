"""PDF metadata heuristics: title, authors, venue, year, DOI/arXiv."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

STOP = {"a", "an", "the", "of", "for", "and", "on", "in", "to", "with",
        "towards", "via", "using", "from", "by", "at", "as", "is", "are"}
VENUES = [
    ("usenixsecurity", r"USENIX\s+Security"),
    ("infocom", r"\bINFOCOM\b"),
    ("sigcomm", r"\bSIGCOMM\b"),
    ("nsdi", r"\bNSDI\b"),
    ("imc", r"\bIMC\b|Internet Measurement Conference"),
    ("conext", r"\bCoNEXT\b"),
    ("hotnets", r"\bHotNets\b"),
    ("ccs", r"\bCCS\b|Computer and Communications Security"),
    ("sp", r"IEEE\s+S&P|Symposium on Security and Privacy"),
    ("ton", r"IEEE/ACM\s+Transactions on Networking"),
    ("jsac", r"\bJSAC\b"),
    ("tcc", r"Transactions on Cloud Computing"),
    ("arxiv", r"arXiv"),
]
AFFIL = re.compile(r"Laborator|Universit|Institut|Department|School|College", re.I)


def kebab(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def short_title(title: str) -> str:
    base = title.split(":", 1)[0] if ":" in title else title
    words = [w for w in re.findall(r"[A-Za-z0-9]+", base.lower()) if w not in STOP]
    if not words:
        words = re.findall(r"[A-Za-z0-9]+", title.lower())[:3]
    return kebab("-".join(words[:3]))[:40].strip("-") or "paper"


def detect_venue(text: str) -> tuple[str | None, int | None]:
    for token, pat in VENUES:
        m = re.search(pat, text, re.I)
        if m:
            window = text[max(0, m.start() - 100):m.end() + 100]
            y = re.search(r"\b(20\d\d)\b", window)
            return token, int(y.group(0)) if y else None
    return None, None


def detect_metadata(pdf: Path) -> dict:
    doc = pymupdf.open(pdf)
    page = doc[0]
    lines = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if text:
                lines.append((max(s["size"] for s in ln["spans"]), text,
                              pymupdf.Rect(ln["bbox"])))
    title, title_bottom = pdf.stem, 0.0
    if lines:
        big = max(s for s, _, _ in lines)
        chosen = [(s, t, b) for s, t, b in lines if s >= big - 0.6]
        title = re.sub(r"\s+", " ", " ".join(t for _, t, _ in chosen)).strip()
        title_bottom = max(b.y1 for _, _, b in chosen)

    abs_y = None
    for b in page.get_text("blocks"):
        if re.match(r"^\s*abstract\b", b[4], re.I):
            abs_y = b[1]
            break
    authors = []
    for b in page.get_text("blocks"):
        text = re.sub(r"\s+", " ", b[4]).strip()
        if b[1] >= title_bottom and (abs_y is None or b[3] < abs_y) \
                and len(text) < 300 and not AFFIL.search(text) and "@" not in text:
            authors.append(text)
    authors = ", ".join(a.rstrip(" ,;") for a in authors[:2])

    head = "\n".join(doc[i].get_text() for i in range(min(3, doc.page_count)))
    venue, year = detect_venue(head)
    if not year:
        m = re.search(r"D:(\d{4})", doc.metadata.get("creationDate", "") or "")
        year = int(m.group(1)) if m else None
    doi = None
    m = re.search(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", head)
    if m:
        doi = m.group(1).rstrip(".")
    arxiv = None
    m = re.search(r"arXiv[:\s]+(\d{4}\.\d{4,5})", head, re.I)
    if m:
        arxiv = m.group(1)
    return {"title_en": title, "authors": authors, "venue": venue,
            "year": year, "doi": doi, "arxiv": arxiv, "pages": doc.page_count}
