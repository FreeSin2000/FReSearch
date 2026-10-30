#!/usr/bin/env python3
"""Prepare / assemble an English-Markdown -> Chinese-Markdown translation.

The LLM does the translating; these commands only split the work into chunks and
verify the assembled result. Nothing here calls a network service.

    translate.py prepare  papers/<slug> [--target-chars 6000] [--force]
    translate.py assemble papers/<slug> [--strict]

Layout:
    papers/<slug>/md/paper.md          source (English)
    papers/<slug>/zh/chunks/0001.md    chunk handed to the LLM
    papers/<slug>/zh/chunks/0001.zh.md LLM output for that chunk
    papers/<slug>/zh/manifest.json     chunk plan + per-chunk counters
    papers/<slug>/zh/paper.zh.md       assembled translation
    papers/<slug>/zh/translation-report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HEADING = re.compile(r"^#{1,6}\s+", re.M)
TABLE_ROW = re.compile(r"^\|", re.M)
IMAGE = re.compile(r"!\[[^\]]*\]\(pics/[^)]+\)")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def counts(text: str) -> dict:
    return {
        "chars": len(text),
        "headings": len(HEADING.findall(text)),
        "table_rows": len(TABLE_ROW.findall(text)),
        "images": len(IMAGE.findall(text)),
    }


def split_sections(text: str) -> list[str]:
    """Split before level-2 headings, keeping the heading with its body."""
    parts: list[str] = []
    buf: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("## ") and buf:
            parts.append("".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        parts.append("".join(buf))
    return parts


def chunk_sections(sections: list[str], target: int) -> list[str]:
    chunks: list[str] = []
    cur = ""
    for sec in sections:
        if cur and len(cur) + len(sec) > target:
            chunks.append(cur)
            cur = sec
        elif len(sec) > target:
            if cur:
                chunks.append(cur)
                cur = ""
            # oversized single section: split on blank lines
            buf = ""
            for para in sec.split("\n\n"):
                if buf and len(buf) + len(para) + 2 > target:
                    chunks.append(buf + "\n\n")
                    buf = para
                else:
                    buf = (buf + "\n\n" + para) if buf else para
            if buf:
                chunks.append(buf + "\n")
        else:
            cur = (cur + "\n" + sec) if cur else sec
    if cur:
        chunks.append(cur)
    return chunks


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def prepare(paper_dir: Path, target: int, force: bool) -> int:
    md_path = paper_dir / "md" / "paper.md"
    if not md_path.exists():
        sys.exit(f"error: missing {md_path}")
    text = md_path.read_text(encoding="utf-8")
    digest = sha256(text)
    zh = paper_dir / "zh"
    manifest_path = zh / "manifest.json"

    if manifest_path.exists() and not force:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("source_sha256") == digest:
            print(f"prepare: reuse {len(old['chunks'])} chunks (source unchanged)")
            return 0

    chunks = [c.strip("\n") + "\n" for c in chunk_sections(split_sections(text), target)]
    manifest = {
        "source": "md/paper.md",
        "source_sha256": digest,
        "created_at": now(),
        "target_chars": target,
        "chunks": [],
    }
    for i, chunk in enumerate(chunks, start=1):
        cid = f"{i:04d}"
        rel = f"chunks/{cid}.md"
        atomic_write(zh / rel, chunk)
        # remove a stale translation for a re-planned chunk
        stale = zh / f"chunks/{cid}.zh.md"
        if stale.exists():
            stale.unlink()
        manifest["chunks"].append({"id": cid, "file": rel, **counts(chunk)})
    atomic_write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"prepare: {len(chunks)} chunks -> {zh / 'chunks'}")
    print("next: translate every 000N.md into 000N.zh.md, then run assemble")
    return 0


def assemble(paper_dir: Path, strict: bool) -> int:
    zh = paper_dir / "zh"
    manifest_path = zh / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"error: missing {manifest_path}; run prepare first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    md_path = paper_dir / "md" / "paper.md"
    problems: list[str] = []
    if md_path.exists() and sha256(md_path.read_text(encoding="utf-8")) != manifest["source_sha256"]:
        problems.append("md/paper.md changed since prepare; re-run prepare")

    out: list[str] = []
    report_chunks = []
    for ch in manifest["chunks"]:
        cid = ch["id"]
        zh_path = zh / f"chunks/{cid}.zh.md"
        if not zh_path.exists() or not zh_path.read_text(encoding="utf-8").strip():
            problems.append(f"missing translation: chunks/{cid}.zh.md")
            continue
        text = zh_path.read_text(encoding="utf-8").strip() + "\n"
        got = counts(text)
        expect = {k: ch[k] for k in ("headings", "table_rows", "images")}
        for key, want in expect.items():
            if got[key] != want:
                msg = f"chunk {cid}: {key} {got[key]} != source {want}"
                (problems.append if strict else print)("WARN " + msg)
        out.append(text)
        report_chunks.append({"id": cid, **got})

    if problems:
        for p in problems:
            print("FAIL " + p)
        print(f"assemble: {len(problems)} problem(s); not writing paper.zh.md")
        return 1

    result = "\n\n".join(out)
    atomic_write(zh / "paper.zh.md", result)
    report = {
        "source_sha256": manifest["source_sha256"],
        "assembled_at": now(),
        "chunks": report_chunks,
        **{f"total_{k}": v for k, v in counts(result).items()},
    }
    atomic_write(zh / "translation-report.json",
                 json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"assemble: wrote {zh / 'paper.zh.md'} ({len(out)} chunks, {report['total_chars']} chars)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="split md/paper.md into translation chunks")
    p.add_argument("paper_dir")
    p.add_argument("--target-chars", type=int, default=6000)
    p.add_argument("--force", action="store_true")
    a = sub.add_parser("assemble", help="merge chunks and verify structure")
    a.add_argument("paper_dir")
    a.add_argument("--strict", action="store_true",
                   help="structural mismatches are failures instead of warnings")
    args = ap.parse_args()

    paper_dir = Path(args.paper_dir).resolve()
    if not paper_dir.is_dir():
        sys.exit(f"error: not a directory: {paper_dir}")
    if args.cmd == "prepare":
        return prepare(paper_dir, args.target_chars, args.force)
    return assemble(paper_dir, args.strict)


if __name__ == "__main__":
    sys.exit(main())
