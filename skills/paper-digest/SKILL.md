---
name: paper-digest
description: Turn an English paper.md into a Chinese five-layer digest (L0 one-liner, L1 concise, L2 detailed, L3 problem/method deep dive, L4 structured fingerprint plus explicit relations) and validate it. Use after paper2md, when a digest is stale, or when relations must be extracted. No full-text translation and no fabrication; every number needs an anchor.
license: MIT
compatibility: Requires the repo venv (scripts/bootstrap_env.sh) and scripts/validate_digest.py. Reads papers/<slug>/md/paper.md; writes papers/<slug>/digest/.
---

# paper-digest

Produce the Chinese summary layer for one paper. Input is the **English**
`md/paper.md`; output is `digest/digest.zh.md` (L0/L1/L2) and
`digest/digest.json` (L3 fingerprint + relations).

## Preconditions

1. `md/paper.md` exists and passed the paper2md quality gates (G1).
2. Read, in order: `specs/conventions.md`, `specs/digest-schema.md`,
   `specs/relations.md`, `specs/quality-gates.md`.
3. Read `meta.json` for slug/venue/year — do not guess them from the PDF.

If `paper.md` is missing or empty: stop and run the paper2md skill first.

## Output contract

- `digest/digest.zh.md`: exactly the sections in `digest-schema.md` §4
  (`## L0` / `## L1` / `## L2` + five L2 subsections / `## L3 深度剖析`
  + five L3 subsections).
- `digest/digest.json`: every field in `digest-schema.md` §1; unknown fields are
  not allowed. `paper_id` must equal the directory slug.

## Workflow

### 1. Read in chunks (never the whole file at once)

Read `paper.md` in 3–4 passes, tracking line ranges:

| Pass | Sections | Purpose |
|---|---|---|
| A | Title, abstract, I–II | problem, gap, insight, contributions |
| B | III–IV (method) | method components, assumptions |
| C | V (evaluation) + VI | data, baselines, metrics, numbers, limitations |
| D | references | only to resolve citation targets for relations |

Use `grep -n` to jump to sections. For long papers, summarize each pass in 5–8
bullet notes before writing prose.

### 2. Write L0 (one sentence)

Problem + method + key result, ≤60 Chinese characters. No hype adjectives, no
numbers that are not in `paper.md`.

### 3. Write L1 (5–8 bullets, 150–300 chars)

Cover: problem, gap, method, key result, comparison/baseline, limitation.
Each bullet one fact; no nested bullets.

### 4. Write L2 (1500–2500 chars, section by section)

Subsections in this order: 背景与问题 / 方法 / 实验设置 / 主要结果 /
局限与可拓展点.

- Every factual paragraph ends with at least one anchor (`§V-C`, `Fig. 6`, `Table VI`).
- Numbers keep the paper's units and precision; never round silently.
- Explain mechanisms in your own words, but do not add claims the paper does not make.
- “可拓展点” may be your own inference, but mark it as inference (「可进一步……」),
  not as the authors' claim.

### 5. Write L3 deep dive (problem + method only)

This is longer than L2 but deliberately narrow: **no result dumping, no
workload summary, no “our method is better” rhetoric**. A reader should be able
to restate the authors' reasoning and judge the argument.

- `现有方法的痛点`: for each pain point write symptom → why the existing approach
  cannot fix it → evidence (§/Fig./Table). Do not just list weaknesses.
- `问题的本质`: name the structural cause (missing information, wrong
  assumption, incentives, measurement bias, complexity). Separate engineering
  limits from fundamental conflicts.
- `突破思路`: what viewpoint/assumption/signal the paper changes, and why that
  bypasses the pain points.
- `方法如何实现`: inputs/outputs, components in order, key formulas, thresholds,
  parameters, complexity or engineering constraints. Aim for “reproducible idea”.
- `如何证明`: the argument chain — which property is established first, then which
  experiment answers which doubt (external ground truth, ablation, baselines,
  robustness, deployment). Mention a number only when it carries the argument.

Do not pad L3 to hit the length: 2500–5000 Chinese characters, ≥8 anchors.

### 6. Build digest.json

Fill every field. Rules that matter:

- `method[]` names must be the paper's names (PathRadar, XGBoost, …), `role` one sentence.
- `data[].scale` unknown → `"unknown"`, never invent counts.
- `headline_results[].value` must be copied verbatim from `paper.md` (validator greps it).
- `limitations` empty if the authors state none; say so in L2 instead of inventing.
- `keywords`: ≥3, `en` uses the paper's own term (feeds search + relation derivation).
- `doi`/`arxiv` unknown → `null`.

### 7. Extract explicit relations only

For each relation type in `specs/relations.md` §3, scan the text for explicit
statements. Rules:

- Evidence required; `unverified` is rejected for explicit edges.
- Target naming: `paper:<slug>` if already in `index/catalog.jsonl`, else
  `ext:<first-author><year>:<short-title>`.
- Do **not** create `comparable_with` / `same_method` / `same_dataset` — those are
  derived by `scripts/build_graph.py` in P6.
- When unsure, drop the edge. A missing edge is cheaper than a wrong one.

### 8. Validate

```bash
ROOT="$(git rev-parse --show-toplevel)"
"$ROOT/.venv/bin/python" "$ROOT/scripts/validate_digest.py" \
    "$ROOT/papers/<slug>" --strict
```

- `0 error(s)` is required; `0 warning(s)` is the goal under `--strict`.
- On failure, fix the digest, not `paper.md`. If the paper truly lacks the data
  (e.g. no limitations), leave the field empty and explain in L2.

### 9. Report

Report: output paths, L0/L1/L2/L3 character counts, number of methods/keywords/edges,
validator output, and anything marked 存疑. Then stop; do not update `index/`
(that is the ingest step, P5).

## Language rules

- Simplified Chinese; key terms first occurrence with English in parentheses,
  e.g. 「偏好行为（affinity behavior）」.
- Keep `AS`, `BGP`, `XGBoost`, `PathRadar` and other proper nouns in English.
- Keep section numbers, figure/table labels, formulas and units unchanged.
- Use `specs/terms.md` for canonical translations and search aliases.

## Anti-hallucination checklist

- [ ] Every number in L2 appears in `paper.md` (spot-check with grep).
- [ ] Every `headline_results[].value` appears literally in `paper.md`.
- [ ] Every evidence anchor resolves to a real heading/figure/table.
- [ ] Venue/year come from `meta.json`, not from memory.
- [ ] No claim attributed to the authors that is actually your inference.
- [ ] Uncertain items are marked 存疑 / `unverified`, not smoothed over.

## Do not

- Do not translate the full text (that is `--translate`, P5).
- Do not turn L3 into a results section: no “significant/2.3x/first” sales language.
- Do not edit `md/paper.md` or the PDF.
- Do not write `index/` or `meta.json` (P5 orchestration owns them).
- Do not add relation types beyond `specs/relations.md`.
- Do not shorten L2 by dropping required subsections; shorten prose instead.
