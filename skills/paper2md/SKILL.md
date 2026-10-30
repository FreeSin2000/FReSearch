---
name: paper2md
description: Convert a two-column (IEEE/ACM-style) research paper PDF into Markdown with real paragraphs, Markdown tables and cropped vector figures. Use when a paper PDF is added to papers/_inbox, when a paper needs re-conversion, or when figures/tables must be extracted. Includes an optional English-Markdown → Chinese-Markdown translation step. Lightweight PyMuPDF only; no OCR, no ML, no network.
license: MIT
compatibility: Requires the repo venv from scripts/bootstrap_env.sh (Python 3.12, pymupdf==1.28.2, pypdf==6.21.2). Works offline after setup.
---

# paper2md

Turn a **two-column research paper PDF** (IEEE/ACM style) into a paragraph-correct
Markdown file plus its figures and tables.

> **v1 scope: two-column papers only.** The script still contains a per-page
> one-column fallback and a `--single-column` flag, but that path is **not
> validated** in FReSearch yet. Do not claim single-column support; if a
> single-column paper fails, report it instead of hacking the converter.

## When to use

- A new PDF is in `papers/_inbox/` and needs `md/paper.md`.
- An existing `paper.md` is stale (source PDF changed) and must be regenerated.
- Figures or tables are missing/wrong and need a re-crop.
- The user explicitly asks for a Chinese full-text translation (`--translate`).

Do **not** use for: book chapters, LaTeX sources, scanned PDFs (no text layer),
or non-paper documents. Refuse and explain.

## Setup (once per machine)

The venv is shared by all skills and lives at the repo root:

```bash
ROOT="$(git rev-parse --show-toplevel)"     # or $FRESEARCH_ROOT
bash "$ROOT/scripts/bootstrap_env.sh"       # idempotent: reuse if complete
```

Never create a per-task venv, never `pip install` into system Python.

## Workflow

```bash
ROOT="$(git rev-parse --show-toplevel)"
SLUG=infocom2025-affinity-model
PY="$ROOT/.venv/bin/python"
S="$ROOT/skills/paper2md/scripts/paper2md.py"

"$PY" "$S" "$ROOT/papers/$SLUG/source/paper.pdf" \
      -o "$ROOT/papers/$SLUG/md" --name paper
```

Output:

```
papers/<slug>/md/
├── paper.md          # English Markdown (never translated by default)
├── pics/figN.png     # one crop per figure
└── figures.json      # label, caption, page, clip, file
```

Useful flags:

| Flag | Meaning |
|---|---|
| `--dpi 200` | figure crop resolution (default 200) |
| `--name paper` | output basename (keep `paper`) |
| `--single-column` | **experimental**, unvalidated; do not use in v1 |

The script prints `wrote … (N figures)`. A PyMuPDF "Consider using
pymupdf_layout" notice on stderr is harmless.

## How it works

1. **Text** — PyMuPDF `get_text("blocks")`, one block ≈ one paragraph; blocks are
   ordered left column then right column. This is why pypdf is not used: it
   flattens paragraphs and mangles small-caps headings.
2. **Mask figures/tables** — blocks whose centre lies inside a figure crop or a
   detected table are dropped, so axis labels do not leak into prose.
3. **Figures** — for each `Fig. N:` caption, crop the union of vector drawing
   rects in the caption's column, above the caption and below the previous
   caption in that column. Vector drawing rects, not embedded-image boxes.
4. **Tables** — `page.find_tables()`, kept only when a `TABLE n:` caption sits
   just below; emit a Markdown table. The caption filter rejects chart axes.
5. **Polish** — merge wrapped subtitle into title, peel headings merged into
   paragraphs, escape a leading `#` in prose, split references on `[n]`,
   de-hyphenate soft line breaks using the document's own vocabulary.

## Two-column layout rules

- Two- vs one-column is decided **per page**, never globally.
- Within a page, blocks sort by `(column, y)`. Sorting by `y` alone interleaves
  the columns and corrupts every paragraph.
- Figure crops are **per column**: the crop stays inside the caption's column,
  bounded below by the previous caption in that column.
- `TABLE` captions are often centred across the full page width, so associate
  tables with captions by vertical distance only, not by column.
- Subfigure labels `(a)`, `(b)` may appear as their own lines before the image;
  harmless.

## Quality gates (run before reporting success)

```bash
cd "$ROOT/papers/$SLUG/md"

# 1. every referenced image exists
grep -oE 'pics/[^)]+' paper.md | while read p; do [ -f "$p" ] || echo "missing $p"; done

# 2. figure / table counts match figures.json and the PDF
grep -c '^\*Fig\.' paper.md
grep -c '^\*Table' paper.md
"$PY" -c "import json;print(len(json.load(open('figures.json'))))"

# 3. headings exist and are ordered
grep -n '^#' paper.md

# 4. no leaked running headers / copyright lines
grep -nEi 'authorized licensed use|downloaded on .* from ieee|restrictions apply' paper.md
```

Pass criteria: no `missing`, figure count == `figures.json` length == captions,
table count matches the PDF, headings non-empty and in section order, no leaked
header lines. If any check fails, report the failure; do not silently accept.

Reference run: Affinity-Model (INFOCOM 2025), 10 pages, 7 figures, 7 tables,
~390 lines of `paper.md`. Use these numbers to spot regressions.

## Gotchas (hard-won; read before editing the script)

- **Vector vs bitmap**: `get_image_info()` finds almost nothing in a paper;
  `get_drawings()` is what works.
- **`Fig. N:` vs `Fig. X.Y`**: accept both numbering styles.
- **Small-caps headings**: pypdf turns `INTRODUCTION` into `I NTRODUCTION`; use
  PyMuPDF blocks instead.
- **Merged headings**: `V. EVALUATION` and `A. Overview` sometimes share a block
  with the next paragraph; peel leading heading lines.
- **`#` in prose**: `#hits / #d2a` must be escaped or it becomes an H1.
- **De-hyphenation**: build the vocabulary **after** normalizing `-\n`; building
  it from raw text makes fragments (`evolu`, `deci`) look like real words and
  keeps every soft hyphen.

## Optional: translate English Markdown → Chinese Markdown

Only when the user explicitly asks. The default pipeline never translates;
the ingest-level `--translate` switch is implemented in P5, so for now treat this
as a manual, opt-in step.

- Input: `md/paper.md`; output: `zh/paper.zh.md`.
- Translate in 3–4 chunks (e.g. abstract+intro, method, evaluation, related+refs),
  appending each chunk; do not rewrite the file from scratch each time.
- Preserve: heading levels, Markdown tables, code, math, figure/table numbers
  and captions, `[n]` citations. Do not translate in-figure text.
- Terms: keep the English original in parentheses on first use,
  e.g. 「偏好行为（affinity behavior）」.
- Cost: input ≈ words × 1.33 tokens; Chinese output ≈ 1.0–1.5 tokens/char;
  a 7k-word paper ≈ 30–35k tokens including overhead.

## Limits

- Math is whatever the PDF text layer stores; multi-line equations may flatten
  into the surrounding paragraph. This is a reading aid, not LaTeX-faithful.
- Tables with merged cells or rotated headers may need a manual touch-up.
- Figures keep in-figure text in the source language (only captions are text).
- Scanned PDFs are refused, not OCR'd.
- A bad path or corrupt PDF exits non-zero with a traceback; capture the message
  and report it, do not retry blindly.
- Soft hyphenation is heuristic: rare cases keep a hyphen (e.g. `Inter-net`).
  Known edge case, not fixed in the migration step.
