#!/usr/bin/env python3
"""Build index/graph.jsonl and index/compare.md from digest.json files.

Explicit edges come from each digest's `relations` (evidence required). Derived
edges are computed here with fixed rules from specs/relations.md - no LLM.

    build_graph.py [--json]

Rules:
  comparable_with  shared >=2 keywords.en AND shared >=1 data.name or metric
  same_method      normalized method names intersect
  same_dataset     normalized data names intersect
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "papers"
INDEX = ROOT / "index"

REL_TYPES = ("builds_on", "compares_to", "uses_method", "uses_dataset",
             "extends", "contradicts", "applies_to")
SYMMETRIC = {"comparable_with", "same_method", "same_dataset"}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def squash(s: str) -> str:
    """For names: 'Route Views' and 'RouteViews' must match."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def load_digests() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(PAPERS.glob("*/digest/digest.json")):
        slug = path.parent.parent.name
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"warning: skip {path}: {exc}", file=sys.stderr)
            continue
        obj["_slug"] = slug
        out[slug] = obj
    return out


def _names(items, key: str) -> dict[str, str]:
    """squashed name -> original display name"""
    out = {}
    for item in items or []:
        val = item.get(key, "") if isinstance(item, dict) else str(item)
        if val:
            out.setdefault(squash(val), val)
    return out


def keywords(d: dict) -> dict[str, str]:
    return {norm(k.get("en", "")): k.get("en", "")
            for k in d.get("keywords", []) if k.get("en")}


def datasets(d: dict) -> dict[str, str]:
    return _names(d.get("data"), "name")


def metrics(d: dict) -> dict[str, str]:
    return {squash(m): m for m in d.get("metrics", []) if m}


def methods(d: dict) -> dict[str, str]:
    return _names(d.get("method"), "name")


def edge(from_: str, type_: str, to: str, evidence: str, confidence: str,
         note: str | None = None, matched_on: list[str] | None = None) -> dict:
    e = {"from": f"paper:{from_}", "type": type_, "to": to,
         "evidence": evidence, "confidence": confidence}
    if note:
        e["note"] = note
    if matched_on:
        e["matched_on"] = matched_on
    return e


def explicit_edges(digests: dict[str, dict]) -> list[dict]:
    edges = []
    for slug, d in digests.items():
        relations = d.get("relations") or {}
        for rtype, items in relations.items():
            if rtype not in REL_TYPES:
                continue
            for item in items or []:
                if not isinstance(item, dict) or not item.get("target"):
                    continue
                edges.append(edge(slug, rtype, item["target"],
                                  item.get("evidence", ""),
                                  item.get("confidence", "explicit"),
                                  item.get("note")))
    return edges


def _symmetric(from_: str, type_: str, to: str, matched_on: list[str]) -> dict:
    a, b = sorted((from_, to))
    return edge(a, type_, f"paper:{b}", "derived", "derived", matched_on=matched_on)


def derived_edges(digests: dict[str, dict]) -> list[dict]:
    slugs = sorted(digests)
    edges = []
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            da, db = digests[a], digests[b]
            kw = sorted(set(keywords(da)) & set(keywords(db)))
            ds = sorted(set(datasets(da)) & set(datasets(db)))
            ms = sorted(set(metrics(da)) & set(metrics(db)))
            if len(kw) >= 2 and (ds or ms):
                matched = [f"keyword:{keywords(da)[k]}" for k in kw]
                matched += [f"dataset:{datasets(da)[k]}" for k in ds]
                matched += [f"metric:{metrics(da)[k]}" for k in ms]
                edges.append(_symmetric(a, "comparable_with", b, matched))

            mth = sorted(set(methods(da)) & set(methods(db)))
            if mth:
                edges.append(_symmetric(a, "same_method", b,
                                        [f"method:{methods(da)[k]}" for k in mth]))

            if ds:
                edges.append(_symmetric(a, "same_dataset", b,
                                        [f"dataset:{datasets(da)[k]}" for k in ds]))
    return edges


def dedupe(edges: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for e in edges:
        key = (e["from"], e["type"], e["to"])
        if key not in seen or (seen[key]["confidence"] == "derived"
                               and e["confidence"] == "explicit"):
            seen[key] = e
    return sorted(seen.values(), key=lambda e: (e["type"], e["from"], e["to"]))


def build(digests: dict[str, dict]) -> tuple[list[dict], list[list[str]]]:
    edges = dedupe(explicit_edges(digests) + derived_edges(digests))
    parent = {s: s for s in digests}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for e in edges:
        if e["type"] == "comparable_with":
            a = e["from"].split(":", 1)[1]
            b = e["to"].split(":", 1)[1]
            if a in parent and b in parent:
                union(a, b)
    groups: dict[str, list[str]] = {}
    for s in digests:
        groups.setdefault(find(s), []).append(s)
    clusters = sorted((sorted(g) for g in groups.values() if len(g) > 1),
                      key=lambda g: g[0])
    return edges, clusters


def write_graph(edges: list[dict]) -> None:
    atomic_write(INDEX / "graph.jsonl",
                 "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in edges))


def shared_summary(digests: dict[str, dict], group: list[str]) -> str:
    kws = None
    ds = None
    ms = None
    for s in group:
        d = digests[s]
        kws = set(keywords(d)) if kws is None else kws & set(keywords(d))
        ds = set(datasets(d)) if ds is None else ds & set(datasets(d))
        ms = set(metrics(d)) if ms is None else ms & set(metrics(d))
    parts = []
    if kws:
        parts.append("关键词：" + "、".join(sorted(kws)))
    if ds:
        parts.append("数据集：" + "、".join(sorted(ds)))
    if ms:
        parts.append("指标：" + "、".join(sorted(ms)))
    return "；".join(parts) or "无共同字段"


def write_compare(digests: dict[str, dict], edges: list[dict],
                  groups: list[list[str]]) -> None:
    by_type: dict[str, int] = {}
    for e in edges:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1

    lines = ["# 可比论文组", "",
             "由 `comparable_with` 派生边分组；只列 digest 中已有的字段，不新增判断。", ""]
    if not groups:
        lines.append("_暂无满足条件的可比组（需共享 ≥2 个关键词且共享数据集或指标）。_")
    for n, group in enumerate(groups, start=1):
        lines += [f"## 组 {n}", "", shared_summary(digests, group), "",
                  "| 论文 | 年份 | 会议 | 问题 | 方法 | 代表结果 |",
                  "|---|---|---|---|---|---|"]
        for s in group:
            d = digests[s]
            title = d.get("title", {}).get("zh") or d.get("title", {}).get("en") or s
            problem = (d.get("problem", {}).get("zh") or "").replace("|", "\\|")
            if len(problem) > 70:
                problem = problem[:68] + "…"
            meth = ", ".join(m.get("name", "") for m in d.get("method", [])[:3])
            hr = (d.get("headline_results") or [{}])[0]
            result = f"{hr.get('claim', '')}：{hr.get('value', '')}".strip("：")
            lines.append(f"| {title} | {d.get('year', '?')} | {d.get('venue', '?')} | "
                         f"{problem} | {meth} | {result} |")
        lines.append("")

    lines += ["## 关系统计", ""]
    for t, c in sorted(by_type.items()):
        lines.append(f"- `{t}`: {c}")
    lines += ["", f"_edges: {len(edges)}_"]
    atomic_write(INDEX / "compare.md", "\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    digests = load_digests()
    edges, groups = build(digests)
    write_graph(edges)
    write_compare(digests, edges, groups)

    if args.json:
        print(json.dumps({"papers": sorted(digests), "edges": edges,
                          "groups": groups}, indent=2, ensure_ascii=False))
    else:
        derived = sum(1 for e in edges if e["confidence"] == "derived")
        print(f"graph: {len(edges)} edges ({derived} derived, "
              f"{len(edges) - derived} explicit), {len(groups)} comparable group(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
