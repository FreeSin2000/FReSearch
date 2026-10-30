#!/usr/bin/env python3
"""Build index/catalog.jsonl and index/catalog.md from papers/*/digest.

Run after ingest (and again after a digest is written). Missing digests are not
an error: the paper is listed with digest=false so it stays discoverable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "papers"
INDEX = ROOT / "index"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def first_title(md_path: Path) -> str:
    if not md_path.exists():
        return ""
    for line in md_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def entry_for(paper_dir: Path) -> dict | None:
    meta_path = paper_dir / "meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    digest_path = paper_dir / "digest" / "digest.json"
    digest = None
    if digest_path.exists():
        try:
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            digest = None

    rel = lambda p: str(p.relative_to(ROOT))
    entry = {
        "paper_id": meta.get("slug") or paper_dir.name,
        "slug": meta.get("slug") or paper_dir.name,
        "status": meta.get("status"),
        "digest": digest is not None,
        "title_en": (digest or {}).get("title", {}).get("en") or meta.get("title_en")
        or first_title(paper_dir / "md" / "paper.md"),
        "title_zh": (digest or {}).get("title", {}).get("zh", ""),
        "venue": (digest or {}).get("venue") or meta.get("venue"),
        "year": (digest or {}).get("year") or meta.get("year"),
        "keywords": [k.get("en", "") for k in (digest or {}).get("keywords", []) if k.get("en")],
        "problem_zh": (digest or {}).get("problem", {}).get("zh", ""),
        "method_names": [m.get("name", "") for m in (digest or {}).get("method", []) if m.get("name")],
        "datasets": [d.get("name", "") for d in (digest or {}).get("data", []) if d.get("name")],
        "metrics": (digest or {}).get("metrics", []),
        "headline": ((digest or {}).get("headline_results") or [{}])[0].get("value", ""),
        "stale": [x for x in meta.get("stale", []) if x != "index"],
        "paths": {
            "md": rel(paper_dir / "md" / "paper.md"),
            "digest_md": rel(paper_dir / "digest" / "digest.zh.md"),
            "digest_json": rel(paper_dir / "digest" / "digest.json"),
            "translation": rel(paper_dir / "zh" / "paper.zh.md"),
        },
    }
    return entry


def write_md(entries: list[dict]) -> None:
    lines = [
        "# 论文目录",
        "",
        f"共 {len(entries)} 篇；`digest=no` 表示尚未生成 L0–L3 总结。",
        "",
        "| 论文 | 年份 | 会议/期刊 | 一句话 | 关键词 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for e in entries:
        title = e["title_zh"] or e["title_en"] or e["slug"]
        title = title.replace("|", "\\|")
        problem = (e["problem_zh"] or "").replace("|", "\\|")
        if len(problem) > 60:
            problem = problem[:58] + "…"
        kw = ", ".join(e["keywords"][:4]).replace("|", "\\|")
        flag = "digest=yes" if e["digest"] else "digest=no"
        stale = " (stale)" if e["stale"] else ""
        lines.append(f"| [{title}]({e['paths']['digest_md']}) | {e['year'] or '?'} | "
                     f"{e['venue'] or '?'} | {problem} | {kw} | {flag}{stale} |")
    lines.append("")
    lines.append(f"_generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}_")
    atomic_write(INDEX / "catalog.md", "\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    entries = []
    for d in sorted(PAPERS.iterdir()) if PAPERS.exists() else []:
        if d.is_dir() and not d.name.startswith("_"):
            e = entry_for(d)
            if e:
                entries.append(e)
    entries.sort(key=lambda e: (-(e["year"] or 0), e["slug"]))

    atomic_write(INDEX / "catalog.jsonl",
                 "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))
    write_md(entries)
    if not args.quiet:
        n_digest = sum(1 for e in entries if e["digest"])
        print(f"index: {len(entries)} papers ({n_digest} with digest) -> index/catalog.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
