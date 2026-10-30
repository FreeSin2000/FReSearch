#!/usr/bin/env python3
"""Ingest paper PDFs into papers/<slug>/ (convert, validate, index).

Digesting is done by the LLM via the paper-digest skill; this script prepares the
paper, runs paper2md, checks an existing digest, and rebuilds the index. It is
idempotent and resumable: hashes in meta.json decide which steps rerun.

    ingest.py                          # everything in papers/_inbox
    ingest.py paper.pdf --venue infocom --year 2025
    ingest.py paper.pdf --force --translate
    ingest.py --reindex                # rebuild index only

Status: new -> converted -> digested -> done (failed keeps artifacts).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from lib.mdtext import count_lines
from lib.metadata import detect_metadata, detect_venue, kebab, short_title
from lib.paths import INBOX, PAPERS, ROOT
from lib.store import (atomic_write, load_meta, save_meta, sha256_file,
                       utc_now)

PY = ROOT / ".venv" / "bin" / "python"
PAPER2MD = ROOT / "skills" / "paper2md" / "scripts" / "paper2md.py"
VALIDATE = ROOT / "scripts" / "validate_digest.py"
BUILD_INDEX = ROOT / "scripts" / "build_index.py"
GRAPH = ROOT / "scripts" / "build_graph.py"
TRANSLATE = ROOT / "scripts" / "translate.py"


def find_by_hash(source_hash: str) -> Path | None:
    matches = []
    for meta_path in sorted(PAPERS.glob("*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if meta.get("source_sha256") == source_hash:
            matches.append((meta.get("status"), meta_path.parent))
    if not matches:
        return None
    rank = {"done": 4, "digested": 3, "converted": 2, "new": 1, "failed": 0}
    return max(matches, key=lambda m: rank.get(m[0], -1))[1]


def resolve_slug(info: dict, source_hash: str, override: str | None) -> Path:
    if override:
        base = kebab(override)
    else:
        venue = info["venue"] or "unknown"
        year = info["year"] or "unknown"
        base = f"{venue}{year}-{short_title(info['title_en'])}"
    base = base or "paper"
    candidate, n = base, 2
    while (PAPERS / candidate).exists():
        meta = load_meta(PAPERS / candidate)
        if meta.get("source_sha256") == source_hash:
            return PAPERS / candidate
        candidate = f"{base}-{n}"
        n += 1
    return PAPERS / candidate


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def count_tables(md_path: Path) -> int:
    return count_lines(md_path, "*Table ")


def count_figures(md_path: Path) -> int:
    return count_lines(md_path, "*Fig. ")


def validate_digest(paper_dir: Path) -> tuple[bool, str]:
    r = run([str(PY), str(VALIDATE), str(paper_dir), "--json"])
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        return False, (r.stderr or r.stdout).strip()[:300]
    if out.get("ok"):
        return True, ""
    msgs = [f"{p['where']}: {p['message']}"
            for f in out.get("files", []) for p in f["problems"] if p["level"] == "error"]
    return False, "; ".join(msgs[:3])


def process(pdf: Path, args) -> dict:
    source_hash = sha256_file(pdf)
    result = {"source": str(pdf), "slug": None, "status": None,
              "figures": 0, "tables": 0, "actions": [], "error": None}

    existing = find_by_hash(source_hash)
    if existing:
        paper_dir = existing
        meta = load_meta(paper_dir)
        first_time = False
        result["actions"].append("force: existing paper" if args.force
                                 else "resume: existing paper")
        info = {"title_en": meta.get("title_en", ""), "authors": meta.get("authors", ""),
                "venue": meta.get("venue"), "year": meta.get("year"),
                "doi": meta.get("doi"), "arxiv": meta.get("arxiv")}
    else:
        info = detect_metadata(pdf)
        if args.venue:
            info["venue"] = kebab(args.venue)
        if args.year:
            info["year"] = int(args.year)
        if args.venue and not args.year and not info["year"]:
            print("warning: --venue without --year; slug uses 'unknown'", file=sys.stderr)
        paper_dir = resolve_slug(info, source_hash, args.slug)
        meta = load_meta(paper_dir)
        first_time = not meta

    for sub in ("source", "md", "digest", "zh"):
        (paper_dir / sub).mkdir(parents=True, exist_ok=True)

    if first_time:
        meta = {
            "slug": paper_dir.name, "status": "new",
            "title_en": info["title_en"], "authors": info["authors"],
            "venue": info["venue"], "year": info["year"],
            "doi": info["doi"], "arxiv": info["arxiv"],
            "source_sha256": source_hash,
            "paper_md_sha256": None, "digest_sha256": None,
            "steps": {"converted_at": None, "digested_at": None, "indexed_at": None},
            "stale": [], "translation": {"status": "none"}, "error": None,
        }
    else:
        meta.update(title_en=info["title_en"], authors=info["authors"],
                    venue=info["venue"], year=info["year"],
                    doi=info["doi"], arxiv=info["arxiv"])

    dest = paper_dir / "source" / "paper.pdf"
    if not dest.exists() or sha256_file(dest) != source_hash:
        tmp = dest.with_suffix(".pdf.tmp")
        shutil.copy2(pdf, tmp)
        os.replace(tmp, dest)
        meta["source_sha256"] = source_hash
        had_digest = (paper_dir / "digest" / "digest.json").exists()
        stale = set(meta.get("stale", [])) | {"index"}
        if had_digest:
            stale |= {"digest"}
        meta["stale"] = sorted(stale)
        result["actions"].append("copied source")

    # ---- convert ---------------------------------------------------------- #
    md_path = paper_dir / "md" / "paper.md"
    old_md_hash = sha256_file(md_path) if md_path.exists() else None
    need_convert = (args.force or not md_path.exists()
                    or meta.get("source_sha256") != source_hash
                    or (meta.get("paper_md_sha256") not in (None, old_md_hash)))
    if need_convert:
        r = run([str(PY), str(PAPER2MD), str(dest), "-o", str(paper_dir / "md"),
                 "--name", "paper"])
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip()[-500:])
        new_md_hash = sha256_file(md_path)
        if old_md_hash and old_md_hash != new_md_hash \
                and (paper_dir / "digest" / "digest.json").exists():
            meta["stale"] = sorted(set(meta.get("stale", [])) | {"digest", "index"})
        meta["paper_md_sha256"] = new_md_hash
        meta["status"] = "converted"
        meta["steps"]["converted_at"] = utc_now()
        meta["steps"]["digested_at"] = None
        result["actions"].append("converted")
    else:
        meta["paper_md_sha256"] = old_md_hash
        result["actions"].append("conversion up to date")

    result["figures"] = count_figures(md_path)
    result["tables"] = count_tables(md_path)

    # ---- digest check (the LLM writes it; we only verify) ----------------- #
    digest_json = paper_dir / "digest" / "digest.json"
    if digest_json.exists():
        ok, why = validate_digest(paper_dir)
        if ok and "digest" not in meta.get("stale", []):
            meta["digest_sha256"] = sha256_file(digest_json)
            meta["steps"]["digested_at"] = meta["steps"].get("digested_at") or utc_now()
            meta["status"] = "digested"
            meta["stale"] = [s for s in meta.get("stale", []) if s != "digest"]
            result["actions"].append("digest valid")
        else:
            meta["status"] = "converted"
            meta["stale"] = sorted(set(meta.get("stale", [])) | {"digest"})
            result["actions"].append(f"digest invalid/stale: {why or 'stale'}")
    else:
        if meta.get("status") in ("digested", "done"):
            result["actions"].append("digest removed: status downgraded")
        meta["status"] = "converted"
        meta["digest_sha256"] = None
        meta["steps"]["digested_at"] = None
        result["actions"].append("digest missing")

    # ---- translation (optional) ------------------------------------------ #
    if args.translate:
        r = run([str(PY), str(TRANSLATE), "prepare", str(paper_dir)])
        if r.returncode == 0:
            meta["translation"] = {"status": "prepared",
                                   "source_sha256": meta["paper_md_sha256"]}
            result["actions"].append("translation chunks prepared")
        else:
            result["actions"].append("translation prepare failed: "
                                     + (r.stderr or r.stdout).strip()[:200])

    # ---- index ------------------------------------------------------------ #
    # Persist meta first: build_index reads papers/*/meta.json, so a newly
    # ingested paper must already be on disk.
    meta["error"] = None
    save_meta(paper_dir, meta)
    if not args.no_index:
        r = run([str(PY), str(BUILD_INDEX), "--quiet"])
        g = run([str(PY), str(GRAPH)])
        if r.returncode != 0 or g.returncode != 0:
            result["actions"].append("index failed: "
                                     + (r.stderr or r.stdout or g.stderr or g.stdout).strip()[:200])
        else:
            meta["steps"]["indexed_at"] = utc_now()
            if meta["status"] == "digested":
                meta["status"] = "done"
            if "index" in meta.get("stale", []):
                meta["stale"] = [s for s in meta["stale"] if s != "index"]

    meta["error"] = None
    save_meta(paper_dir, meta)
    result.update(slug=paper_dir.name, status=meta["status"])
    if args.move:
        pdf.unlink()
        result["actions"].append("moved from inbox")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*", help="PDF files (default: papers/_inbox/*.pdf)")
    ap.add_argument("--venue", help="override venue token, e.g. usenixsecurity")
    ap.add_argument("--year", type=int, help="override publication year")
    ap.add_argument("--slug", help="override the whole slug")
    ap.add_argument("--force", action="store_true", help="re-convert even if unchanged")
    ap.add_argument("--move", action="store_true", help="move PDF out of inbox")
    ap.add_argument("--translate", action="store_true", help="prepare zh translation chunks")
    ap.add_argument("--no-index", action="store_true", help="skip index rebuild")
    ap.add_argument("--reindex", action="store_true", help="rebuild index only")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.reindex:
        rc = 0
        for script in (BUILD_INDEX, GRAPH):
            r = run([str(PY), str(script)])
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            rc = rc or r.returncode
        return rc

    if args.slug and len(args.pdfs) > 1:
        ap.error("--slug only makes sense for a single PDF")

    pdfs = [Path(p) for p in args.pdfs] if args.pdfs else sorted(INBOX.glob("*.pdf"))
    pdfs = [p for p in pdfs if p.suffix.lower() == ".pdf" and p.is_file()]
    if not pdfs:
        print("nothing to do: no PDFs (put one in papers/_inbox)")
        return 0

    results = []
    for pdf in pdfs:
        try:
            results.append(process(pdf, args))
        except Exception as exc:  # noqa: BLE001 - keep going, report per paper
            results.append({"source": str(pdf), "slug": None, "status": "failed",
                            "figures": 0, "tables": 0, "actions": [],
                            "error": f"{type(exc).__name__}: {exc}"})

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"{r['slug'] or r['source']}: {r['status']}  "
                  f"({r['figures']} figs, {r['tables']} tables)")
            for a in r["actions"]:
                print(f"  - {a}")
            if r["error"]:
                print(f"  ! {r['error']}")
            if r["status"] == "converted":
                print("  next: run the paper-digest skill, then ingest.py --reindex")
            elif r["status"] == "failed":
                print("  next: fix the error and rerun with --force")
    return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
