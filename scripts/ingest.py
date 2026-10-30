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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "papers"
INBOX = PAPERS / "_inbox"
PY = ROOT / ".venv" / "bin" / "python"
PAPER2MD = ROOT / "skills" / "paper2md" / "scripts" / "paper2md.py"
VALIDATE = ROOT / "scripts" / "validate_digest.py"
BUILD_INDEX = ROOT / "scripts" / "build_index.py"
GRAPH = ROOT / "scripts" / "build_graph.py"
TRANSLATE = ROOT / "scripts" / "translate.py"

STOP = {"a", "an", "the", "of", "for", "and", "on", "in", "to", "with",
        "towards", "via", "using", "from", "by", "at", "as", "is", "are"}
VENUES = [
    ("usenixsecurity", r"USENIX\s+Security"),
    ("infocom", r"\bINFOCOM\b"),
    ("sigcomm", r"\bSIGCOMM\b"),
    ("nsdi", r"\bNSDI\b"),
    ("imc", r"\bIMC\b|Internet Measurement Conference"),
    ("conext", r"\bCoNEXT\b"),
    ("ccs", r"\bCCS\b|Computer and Communications Security"),
    ("sp", r"IEEE\s+S&P|Symposium on Security and Privacy"),
    ("ton", r"IEEE/ACM\s+Transactions on Networking"),
    ("jsac", r"\bJSAC\b"),
    ("tcc", r"Transactions on Cloud Computing"),
    ("arxiv", r"arXiv"),
]
AFFIL = re.compile(r"Laborator|Universit|Institut|Department|School|College", re.I)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_meta(paper_dir: Path) -> dict:
    p = paper_dir / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_meta(paper_dir: Path, meta: dict) -> None:
    atomic_write(paper_dir / "meta.json",
                 json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


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
            "year": year, "doi": doi, "arxiv": arxiv,
            "pages": doc.page_count}


def find_by_hash(source_hash: str) -> Path | None:
    for meta_path in PAPERS.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if meta.get("source_sha256") == source_hash:
            return meta_path.parent
    return None


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
    if not md_path.exists():
        return 0
    return sum(1 for line in md_path.read_text(encoding="utf-8").splitlines()
               if line.startswith("*Table "))


def count_figures(md_path: Path) -> int:
    if not md_path.exists():
        return 0
    return sum(1 for line in md_path.read_text(encoding="utf-8").splitlines()
               if line.startswith("*Fig. "))


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
    if existing and not args.force:
        paper_dir = existing
        meta = load_meta(paper_dir)
        first_time = False
        result["actions"].append("resume: existing paper")
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
        meta["steps"]["converted_at"] = now()
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
            meta["steps"]["digested_at"] = meta["steps"].get("digested_at") or now()
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
            meta["steps"]["indexed_at"] = now()
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
