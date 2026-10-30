#!/usr/bin/env python3
"""Validate FReSearch digest artifacts against specs/digest-schema.md.

Checks
------
* digest.json: required fields, types, enums, relation targets, evidence format.
* digest.zh.md: required headings, L0/L1/L2 lengths, Chinese-first heuristic.
* --paper-md: evidence anchors resolve, headline numbers appear in paper.md.

Stdlib only. Exit 0 = no errors (warnings allowed), 1 = errors, 2 = usage/IO.

Usage
-----
    validate_digest.py papers/<slug>                 # auto-find digest/*, md/paper.md
    validate_digest.py path/to/digest.json --paper-md path/to/paper.md
    validate_digest.py papers/<slug> --json --strict
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lib.evidence import EVIDENCE_TOKEN, norm_label, parse_md_anchors
from lib.mdtext import cjk_count, parse_md_sections

SCHEMA_VERSION = "1"
REL_TYPES = (
    "builds_on", "compares_to", "uses_method", "uses_dataset",
    "extends", "contradicts", "applies_to",
)
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TARGET_RE = re.compile(r"^(paper:[a-z0-9-]+|ext:[a-z0-9]+:[a-z0-9-]+|dataset:[a-z0-9-]+)$")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*%?")

MD_SECTIONS = ("L0 一句话", "L1 简洁总结", "L2 详细总结", "L3 深度剖析")
L2_SECTIONS = ("背景与问题", "方法", "实验设置", "主要结果", "局限与可拓展点")
L3_SECTIONS = ("现有方法的痛点", "问题的本质", "突破思路", "方法如何实现", "如何证明")
L0_MAX = 60
L1_RANGE = (150, 300)
L2_RANGE = (1500, 2500)
L3_RANGE = (2500, 5000)
@dataclass
class Problem:
    level: str          # "error" | "warning"
    where: str          # JSON path or markdown heading
    msg: str

    def as_dict(self) -> dict:
        return {"level": self.level, "where": self.where, "message": self.msg}


@dataclass
class Report:
    problems: list[Problem] = field(default_factory=list)

    def err(self, where: str, msg: str) -> None:
        self.problems.append(Problem("error", where, msg))

    def warn(self, where: str, msg: str) -> None:
        self.problems.append(Problem("warning", where, msg))

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.level == "error"]

    @property
    def warnings(self) -> list[Problem]:
        return [p for p in self.problems if p.level == "warning"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def is_nonempty_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def is_int(v) -> bool:
    return type(v) is int


def check_evidence(rep: Report, value, where: str, *, allow_unverified: bool) -> None:
    if not is_nonempty_str(value):
        rep.err(where, "missing evidence")
        return
    parts = [p.strip() for p in re.split(r"[;/]", value) if p.strip()]
    if not parts:
        rep.err(where, "empty evidence")
        return
    for part in parts:
        if not EVIDENCE_TOKEN.match(part):
            rep.err(where, f"unrecognized evidence token: {part!r}")
        elif part == "unverified" and not allow_unverified:
            rep.err(where, "unverified evidence not allowed here")


def check_bilingual(rep: Report, obj, key: str, where: str) -> None:
    if key not in obj:
        return
    node = obj.get(key)
    if not isinstance(node, dict):
        rep.err(where, f"{key} must be an object with zh/en")
        return
    for lang in ("zh", "en"):
        if not is_nonempty_str(node.get(lang)):
            rep.err(f"{where}.{key}.{lang}", "non-empty string required")


def check_str_list(rep: Report, obj, key: str, where: str, *, min_len: int = 0) -> None:
    if key not in obj:
        return
    node = obj.get(key)
    if not isinstance(node, list):
        rep.err(where, f"{key} must be an array")
        return
    if len(node) < min_len:
        rep.err(where, f"{key} needs at least {min_len} item(s)")
    for i, item in enumerate(node):
        if not is_nonempty_str(item):
            rep.err(f"{where}.{key}[{i}]", "non-empty string required")


def check_object_list(rep: Report, obj, key: str, fields: tuple[str, ...],
                      where: str, *, min_len: int = 0) -> None:
    if key not in obj:
        return
    node = obj.get(key)
    if not isinstance(node, list):
        rep.err(where, f"{key} must be an array")
        return
    if len(node) < min_len:
        rep.err(where, f"{key} needs at least {min_len} item(s)")
    for i, item in enumerate(node):
        if not isinstance(item, dict):
            rep.err(f"{where}.{key}[{i}]", "object required")
            continue
        for name in fields:
            if not is_nonempty_str(item.get(name)):
                rep.err(f"{where}.{key}[{i}].{name}", "non-empty string required")


# --------------------------------------------------------------------------- #
# digest.json
# --------------------------------------------------------------------------- #
def validate_digest_object(obj: dict, *, slug: str | None = None,
                           paper_md: str | None = None) -> Report:
    rep = Report()
    if not isinstance(obj, dict):
        rep.err("$", "digest.json must be an object")
        return rep

    required = [
        "schema_version", "paper_id", "title", "venue", "year", "doi", "arxiv",
        "problem", "gap", "insight", "method", "assumptions", "data",
        "baselines", "metrics", "headline_results", "limitations",
        "keywords", "relations",
    ]
    for key in required:
        if key not in obj:
            rep.err("$", f"missing required field: {key}")
    for key in obj:
        if key not in required:
            rep.warn("$", f"unknown field: {key}")

    if obj.get("schema_version") != SCHEMA_VERSION:
        rep.err("schema_version", f"must be {SCHEMA_VERSION!r}")

    pid = obj.get("paper_id")
    if not is_nonempty_str(pid) or not SLUG_RE.match(pid or ""):
        rep.err("paper_id", "must match ^[a-z0-9]+(-[a-z0-9]+)*$")
    elif slug and pid != slug:
        rep.err("paper_id", f"{pid!r} != directory slug {slug!r}")

    title = obj.get("title")
    if "title" not in obj:
        pass
    elif not isinstance(title, dict):
        rep.err("title", "object with en/zh required")
    else:
        for lang in ("en", "zh"):
            if not is_nonempty_str(title.get(lang)):
                rep.err(f"title.{lang}", "non-empty string required")

    venue = obj.get("venue")
    if "venue" not in obj:
        pass
    elif not is_nonempty_str(venue):
        rep.err("venue", "non-empty string required")
    elif venue != venue.lower():
        rep.warn("venue", "should be lowercase")

    year = obj.get("year")
    if "year" not in obj:
        pass
    elif not is_int(year) or not (1900 <= year <= 2100):
        rep.err("year", "integer in 1900..2100 required")

    for key in ("doi", "arxiv"):
        if key not in obj:
            continue
        v = obj.get(key)
        if v is not None and not isinstance(v, str):
            rep.err(key, "string or null required")

    for key in ("problem", "gap", "insight"):
        check_bilingual(rep, obj, key, "$")

    check_object_list(rep, obj, "method", ("name", "role", "detail"), "$", min_len=1)
    check_str_list(rep, obj, "assumptions", "$")
    check_object_list(rep, obj, "data", ("name", "scale", "source"), "$")
    check_str_list(rep, obj, "baselines", "$")
    check_str_list(rep, obj, "metrics", "$")

    results = obj.get("headline_results")
    if not isinstance(results, list) or not results:
        rep.err("headline_results", "non-empty array required")
    else:
        for i, item in enumerate(results):
            w = f"headline_results[{i}]"
            if not isinstance(item, dict):
                rep.err(w, "object required")
                continue
            for f in ("claim", "value"):
                if not is_nonempty_str(item.get(f)):
                    rep.err(f"{w}.{f}", "non-empty string required")
            check_evidence(rep, item.get("evidence"), f"{w}.evidence",
                           allow_unverified=True)

    limitations = obj.get("limitations")
    if not isinstance(limitations, list):
        rep.err("limitations", "array required (may be empty)")
    else:
        for i, item in enumerate(limitations):
            w = f"limitations[{i}]"
            if not isinstance(item, dict) or not is_nonempty_str(item.get("text")):
                rep.err(w, "object with non-empty text required")
                continue
            check_evidence(rep, item.get("evidence"), f"{w}.evidence",
                           allow_unverified=True)

    keywords = obj.get("keywords")
    if not isinstance(keywords, list) or len(keywords) < 3:
        rep.err("keywords", "at least 3 items required")
    else:
        for i, item in enumerate(keywords):
            w = f"keywords[{i}]"
            if not isinstance(item, dict):
                rep.err(w, "object required")
                continue
            for lang in ("zh", "en"):
                if not is_nonempty_str(item.get(lang)):
                    rep.err(f"{w}.{lang}", "non-empty string required")

    relations = obj.get("relations")
    if not isinstance(relations, dict):
        rep.err("relations", "object required")
    else:
        for rtype in REL_TYPES:
            if rtype not in relations:
                rep.err("relations", f"missing relation key: {rtype}")
        for rtype, edges in relations.items():
            w = f"relations.{rtype}"
            if rtype not in REL_TYPES:
                rep.warn(w, "unknown relation type")
                continue
            if not isinstance(edges, list):
                rep.err(w, "array required")
                continue
            for i, edge in enumerate(edges):
                ew = f"{w}[{i}]"
                if not isinstance(edge, dict):
                    rep.err(ew, "object required")
                    continue
                target = edge.get("target")
                if not is_nonempty_str(target) or not TARGET_RE.match(target):
                    rep.err(f"{ew}.target", "must be paper:<slug>, ext:<author>:<short> or dataset:<slug>")
                conf = edge.get("confidence")
                if conf not in ("explicit", "derived"):
                    rep.err(f"{ew}.confidence", "explicit or derived required")
                if conf == "derived":
                    if edge.get("evidence") != "derived":
                        rep.err(f"{ew}.evidence", 'derived edge uses evidence "derived"')
                else:
                    check_evidence(rep, edge.get("evidence"), f"{ew}.evidence",
                                   allow_unverified=False)
                if conf == "derived":
                    matched = edge.get("matched_on")
                    if not isinstance(matched, list) or not matched:
                        rep.err(f"{ew}.matched_on", "derived edge needs matched_on")

    if paper_md:
        check_against_paper(rep, obj, paper_md)
    return rep


# --------------------------------------------------------------------------- #
# paper.md cross-checks
# --------------------------------------------------------------------------- #
def check_against_paper(rep: Report, obj: dict, paper_md: str) -> None:
    sections, figs, tables = parse_md_anchors(paper_md)
    norm_md = re.sub(r"\s+", "", paper_md)

    def resolve(evidence: str, where: str) -> None:
        for part in [p.strip() for p in re.split(r"[;/]", evidence) if p.strip()]:
            if part == "unverified":
                continue
            m = re.match(r"^§([IVXLC]+)(?:-([A-Z]))?$", part)
            if m:
                key = m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
                if key not in sections:
                    rep.err(where, f"section anchor not found in paper.md: {part}")
                continue
            m = re.match(r"^§(\d+(?:\.\d+)*)$", part)
            if m:
                if m.group(1) not in sections:
                    rep.err(where, f"section anchor not found in paper.md: {part}")
                continue
            m = re.match(r"^Fig\.\s*(\d+(?:\.\d+)?)$", part)
            if m:
                if m.group(1) not in figs:
                    rep.err(where, f"figure anchor not found in paper.md: {part}")
                continue
            m = re.match(r"^Table\s+([IVXLC]+|\d+)$", part)
            if m:
                if norm_label(m.group(1)) not in tables:
                    rep.err(where, f"table anchor not found in paper.md: {part}")
                continue
            # p. N is not resolvable from Markdown; ignore.

    for i, item in enumerate(obj.get("headline_results") or []):
        if not isinstance(item, dict):
            continue
        ev = item.get("evidence")
        if is_nonempty_str(ev):
            resolve(ev, f"headline_results[{i}].evidence")
        value = item.get("value")
        if is_nonempty_str(value):
            tokens = NUM_RE.findall(value)
            if not tokens:
                rep.warn(f"headline_results[{i}].value",
                         "no numeric token to verify against paper.md")
            for tok in tokens:
                if re.sub(r"\s+", "", tok) not in norm_md:
                    rep.err(f"headline_results[{i}].value",
                            f"number not found in paper.md: {tok}")
    for i, item in enumerate(obj.get("limitations") or []):
        if isinstance(item, dict) and is_nonempty_str(item.get("evidence")):
            resolve(item["evidence"], f"limitations[{i}].evidence")


# --------------------------------------------------------------------------- #
# digest.zh.md
# --------------------------------------------------------------------------- #
def validate_digest_md(text: str) -> Report:
    rep = Report()
    h1, sections = parse_md_sections(text)
    if not h1:
        rep.err("digest.zh.md", "missing H1 title")

    positions = []
    for name in MD_SECTIONS:
        if name not in sections:
            rep.err(name, "section missing")
        else:
            positions.append(list(sections).index(name))
    if len(positions) == len(MD_SECTIONS) and positions != sorted(positions):
        rep.err("digest.zh.md", "L0/L1/L2 must appear in order")

    if "L0 一句话" in sections:
        body = sections["L0 一句话"].strip()
        n = cjk_count(body)
        if n == 0:
            rep.err("L0 一句话", "no Chinese text")
        elif n > L0_MAX:
            rep.warn("L0 一句话", f"{n} Chinese chars > {L0_MAX}")

    if "L1 简洁总结" in sections:
        body = sections["L1 简洁总结"]
        n = cjk_count(body)
        if n == 0:
            rep.err("L1 简洁总结", "no Chinese text")
        elif not (L1_RANGE[0] <= n <= L1_RANGE[1]):
            rep.warn("L1 简洁总结", f"{n} Chinese chars outside {L1_RANGE}")
        bullets = len(re.findall(r"^\s*[-*]\s+", body, re.M))
        if bullets < 5 or bullets > 8:
            rep.warn("L1 简洁总结", f"{bullets} bullets, expected 5-8")

    if "L2 详细总结" in sections:
        body = sections["L2 详细总结"]
        n = cjk_count(body)
        if n == 0:
            rep.err("L2 详细总结", "no Chinese text")
        elif not (L2_RANGE[0] <= n <= L2_RANGE[1]):
            rep.warn("L2 详细总结", f"{n} Chinese chars outside {L2_RANGE}")
        for name in L2_SECTIONS:
            if name not in sections:
                rep.err(f"L2/{name}", "subsection missing")
        anchors = len(re.findall(
            r"(§(?:[IVXLC]+(?:-[A-Z])?|\d+(?:\.\d+)*)|Fig\.\s*\d+|Table\s+\w+)", body))
        if anchors < 5:
            rep.warn("L2 详细总结", f"only {anchors} anchors; expected >=5")

    if "L3 深度剖析" in sections:
        body = sections["L3 深度剖析"]
        n = cjk_count(body)
        if n == 0:
            rep.err("L3 深度剖析", "no Chinese text")
        elif not (L3_RANGE[0] <= n <= L3_RANGE[1]):
            rep.warn("L3 深度剖析", f"{n} Chinese chars outside {L3_RANGE}")
        for name in L3_SECTIONS:
            if name not in sections:
                rep.err(f"L3/{name}", "subsection missing")
        anchors = len(re.findall(
            r"(§(?:[IVXLC]+(?:-[A-Z])?|\d+(?:\.\d+)*)|Fig\.\s*\d+|Table\s+\w+)", body))
        if anchors < 8:
            rep.warn("L3 深度剖析", f"only {anchors} anchors; expected >=8")

    return rep


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def discover(path: Path) -> tuple[Path | None, Path | None, Path | None]:
    """Return (json, md, paper_md) for a file or a paper directory."""
    if path.is_dir():
        return (path / "digest" / "digest.json",
                path / "digest" / "digest.zh.md",
                path / "md" / "paper.md")
    if path.suffix == ".json":
        return path, None, None
    if path.suffix == ".md":
        return None, path, None
    return None, None, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="paper dir, digest.json or digest.zh.md")
    ap.add_argument("--paper-md", help="paper.md for anchor/number cross-checks")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true", help="warnings become failures")
    ap.add_argument("--quiet", action="store_true", help="only print problems")
    args = ap.parse_args()

    files: list[dict] = []
    total_err = total_warn = 0

    for raw in args.paths:
        path = Path(raw)
        if not path.exists():
            files.append({"path": raw, "problems": [
                Problem("error", raw, "path not found").as_dict()]})
            total_err += 1
            continue
        djson, dmd, pmd = discover(path)
        slug = path.name if path.is_dir() else None
        paper_md = None
        if args.paper_md:
            paper_md = Path(args.paper_md).read_text(encoding="utf-8")
        elif pmd and pmd.exists():
            paper_md = pmd.read_text(encoding="utf-8")

        if djson:
            if not djson.exists():
                files.append({"path": str(djson), "problems": [
                    Problem("error", str(djson), "digest.json not found").as_dict()]})
                total_err += 1
            else:
                try:
                    obj = json.loads(djson.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    files.append({"path": str(djson), "problems": [
                        Problem("error", "$", f"invalid JSON: {exc}").as_dict()]})
                    total_err += 1
                else:
                    rep = validate_digest_object(obj, slug=slug, paper_md=paper_md)
                    files.append({"path": str(djson),
                                  "problems": [p.as_dict() for p in rep.problems]})
                    total_err += len(rep.errors)
                    total_warn += len(rep.warnings)

        if dmd:
            if not dmd.exists():
                files.append({"path": str(dmd), "problems": [
                    Problem("error", str(dmd), "digest.zh.md not found").as_dict()]})
                total_err += 1
            else:
                rep = validate_digest_md(dmd.read_text(encoding="utf-8"))
                files.append({"path": str(dmd),
                              "problems": [p.as_dict() for p in rep.problems]})
                total_err += len(rep.errors)
                total_warn += len(rep.warnings)

        if not djson and not dmd:
            files.append({"path": raw, "problems": [
                Problem("error", raw, "unrecognized path type").as_dict()]})
            total_err += 1

    ok = total_err == 0 and not (args.strict and total_warn)
    if args.json:
        print(json.dumps({"ok": ok, "errors": total_err, "warnings": total_warn,
                          "files": files}, indent=2, ensure_ascii=False))
    else:
        for f in files:
            if not args.quiet or f["problems"]:
                print(f"{f['path']}")
                for p in f["problems"]:
                    print(f"  [{p['level'].upper():<7}] {p['where']}: {p['message']}")
        print(f"\n{total_err} error(s), {total_warn} warning(s)"
              + ("  [strict: warnings fail]" if args.strict else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
