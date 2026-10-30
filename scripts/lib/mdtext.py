"""Markdown helpers shared by validators and index builders."""
from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def squash(s: str) -> str:
    """For names: 'Route Views' and 'RouteViews' must match."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def cjk_count(s: str) -> int:
    return len(CJK_RE.findall(s))


def parse_md_sections(text: str) -> tuple[str | None, dict[str, str]]:
    """Return (h1, {heading: body}) where a heading's body includes its descendants."""
    h1 = None
    entries: list[list] = []          # [level, title, lines]
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            level, title = len(m.group(1)), m.group(2)
            if level == 1:
                h1 = h1 or title
            else:
                entries.append([level, title, []])
        elif entries:
            entries[-1][2].append(line)
    sections: dict[str, str] = {}
    for i, (level, title, lines) in enumerate(entries):
        body = list(lines)
        for sub_level, _, sub_lines in entries[i + 1:]:
            if sub_level <= level:
                break
            body.extend(sub_lines)
        sections[title] = "\n".join(body)
    return h1, sections


def count_lines(path, prefix: str) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines()
               if line.startswith(prefix))


def first_h1(path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""
