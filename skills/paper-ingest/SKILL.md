---
name: paper-ingest
description: End-to-end ingestion of paper PDFs - slug, dedupe, conversion, state machine, index, and optional translation chunking. Use when PDFs are dropped in papers/_inbox, when a paper must be re-converted, when the catalog is stale, or when the user asks for a Chinese full-text translation. Orchestrates paper2md, paper-digest and translate.py without duplicating their logic.
license: MIT
compatibility: Requires the repo venv (scripts/bootstrap_env.sh) and scripts/{ingest,build_index,translate}.py. Offline.
---

# paper-ingest

Orchestrate one paper from PDF to indexed artifacts. This skill owns **state and
ordering**; it does not summarize (that is `paper-digest`) and does not translate
words (the LLM does, using chunks prepared here).

## Preconditions

1. `bash scripts/bootstrap_env.sh` passes.
2. Read `specs/conventions.md` (slug, state machine, evidence) and
   `specs/quality-gates.md` before touching a paper.
3. Know the paper's venue/year if the PDF does not print them.

## Commands

```bash
ROOT="$(git rev-parse --show-toplevel)"
PY="$ROOT/.venv/bin/python"

# everything in papers/_inbox (idempotent)
"$PY" "$ROOT/scripts/ingest.py"

# one PDF, metadata overrides
"$PY" "$ROOT/scripts/ingest.py" "$ROOT/papers/_inbox/BEAM.pdf" \
      --venue usenixsecurity --year 2024 --slug usenixsecurity2024-beam

# force a rebuild of the Markdown (digest becomes stale)
"$PY" "$ROOT/scripts/ingest.py" PAPER.pdf --force

# rebuild the catalog only
"$PY" "$ROOT/scripts/ingest.py" --reindex

# prepare Chinese translation chunks (does not translate)
"$PY" "$ROOT/scripts/ingest.py" PAPER.pdf --translate
```

`--json` gives machine-readable output. `--move` removes the PDF from the inbox.

## What ingest does

1. **Hash + dedupe** — `source_sha256`; an already-ingested PDF resumes instead
   of creating a second directory.
2. **Slug** — `<venue><year>-<short-title>`; `--venue/--year/--slug` override
   when the PDF has no venue line (ACM/USENIX camera-ready often does not).
3. **Layout** — `papers/<slug>/{source,md,digest,zh}`; the PDF is copied (not
   moved) unless `--move`.
4. **Convert** — runs `paper2md` only when the source or Markdown hash changed.
5. **Digest check** — validates an existing `digest/digest.json`; missing or
   invalid means `status: converted`.
6. **Index** — rebuilds `index/catalog.jsonl` / `catalog.md` (papers without a
   digest are listed with `digest=false`).
7. **Translation (optional)** — splits `md/paper.md` into
   `zh/chunks/NNNN.md` and writes `zh/manifest.json`.

Status machine: `new → converted → digested → done`; `failed` keeps artifacts.
`--force` re-converts and marks the digest stale; it never deletes a digest.

## Full workflow for one paper

```bash
# 1. convert + metadata
"$PY" "$ROOT/scripts/ingest.py" PAPER.pdf --venue V --year Y

# 2. if status == converted: summarize with the paper-digest skill
#    (read specs/digest-schema.md, write digest/digest.zh.md + digest.json)

# 3. validate + index (ingest re-checks the digest and flips status to done)
"$PY" "$ROOT/scripts/ingest.py" PAPER.pdf

# 4. optional translation
"$PY" "$ROOT/scripts/ingest.py" PAPER.pdf --translate
#    then translate every zh/chunks/NNNN.md -> NNNN.zh.md (same structure,
#    Chinese, terms with English in parentheses), and:
"$PY" "$ROOT/scripts/translate.py" assemble "$ROOT/papers/<slug>" --strict
```

## Translation protocol (chunked, resumable)

- `prepare` splits at `##` headings, ≤ `--target-chars` (default 6000) per chunk.
- Translate chunk by chunk; **never rewrite the whole file at once**. Keep
  headings, tables, `pics/` references and `[n]` citations unchanged.
- If interrupted, only missing `NNNN.zh.md` files need work; `prepare` reuses
  the plan while `md/paper.md` is unchanged.
- `assemble --strict` compares heading / table-row / image counts per chunk with
  the source. A mismatch is a failure: fix the chunk, do not edit the source.
- Output: `zh/paper.zh.md` + `zh/translation-report.json`.

## Quality gates

- Conversion: `7 figs / 7 tables` for Affinity; `11 / 3` for BEAM is the
  current baseline. A sudden drop means the converter regressed.
- Digest: `validate_digest.py papers/<slug> --strict` (see paper-digest).
- Index: `index/catalog.jsonl` parses, `paper_id` unique, paths exist.
- Re-run: a second `ingest.py` must say `resume` / `conversion up to date`, not
  duplicate the directory.

## Failure handling

1. `status: failed` + `error` in `meta.json`; artifacts are kept.
2. Diagnose: bad PDF, missing venue, converter regression, digest invalid.
3. Fix, then re-run with `--force` only if conversion must be redone.
4. Never hand-edit `meta.json` to fake `done`; let ingest validate the digest.
5. Report the failing paper + step; do not continue to later papers silently.

## Do not

- Do not run `paper2md` directly for normal ingestion (ingest tracks hashes).
- Do not write summaries here; hand off to `paper-digest`.
- Do not translate the whole file in one shot.
- Do not commit `papers/` artifacts or `index/` (gitignored by design).
