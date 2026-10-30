"""Evidence anchors: formats, roman/arabic labels and paper.md resolution."""
from __future__ import annotations

import re

EVIDENCE_TOKEN = re.compile(
    r"^(?:§(?:[IVXLC]+(?:-[A-Z])?|\d+(?:\.\d+)*)"
    r"|Fig\.\s*\d+(?:\.\d+)?"
    r"|Table\s+(?:[IVXLC]+|\d+)"
    r"|p\.\s*\d+"
    r"|unverified)$"
)
ROMAN_RE = re.compile(r"^[IVXLC]+$")


def roman_to_int(s: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, prev = 0, 0
    for ch in reversed(s):
        cur = values.get(ch, 0)
        total += -cur if cur < prev else cur
        prev = max(prev, cur)
    return total


def norm_label(s: str) -> str:
    return str(roman_to_int(s)) if ROMAN_RE.match(s) else s


def parse_md_anchors(text: str) -> tuple[set[str], set[str], set[str]]:
    sections: set[str] = set()
    current = None
    figs: set[str] = set()
    tables: set[str] = set()
    for line in text.splitlines():
        # Level 2 = section (IV.), level 3 = subsection (B.). Do not use
        # [IVXLC] on level 3: "C." is a valid roman numeral and a valid letter.
        m = re.match(r"^##\s+([IVXLC]+)\.\s", line)
        if m:
            current = m.group(1)
            sections.add(current)
        mn = re.match(r"^##\s+(\d+(?:\.\d+)*)\s+", line)
        if mn:
            sections.add(mn.group(1))
        mn = re.match(r"^###\s+(\d+(?:\.\d+)*)\s+", line)
        if mn:
            sections.add(mn.group(1))
        m = re.match(r"^###\s+([A-Z])\.\s", line)
        if m and current:
            sections.add(f"{current}-{m.group(1)}")
        if not line.startswith("#"):
            figs.update(re.findall(r"Fig\.\s*(\d+(?:\.\d+)?)\s*:", line))
            tables.update(norm_label(t) for t in
                          re.findall(r"Table\s+([IVXLC]+|\d+)\s*:", line))
    return sections, figs, tables
