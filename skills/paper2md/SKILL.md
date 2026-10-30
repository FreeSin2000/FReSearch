---
name: paper2md
description: Convert a two-column IEEE-, ACM- or USENIX-style research paper PDF into Markdown with real paragraphs, Markdown tables and cropped figures (vector or bitmap). Use when a paper PDF is added to papers/_inbox, when a paper needs re-conversion, or when figures/tables must be extracted. Translation is handled separately by paper-ingest/translate.py. Lightweight PyMuPDF only; no OCR, no ML, no network.
license: MIT
compatibility: Requires the repo venv from scripts/bootstrap_env.sh (Python 3.12, pymupdf==1.28.2, pypdf==6.21.2). Works offline after setup.
---

# paper2md

Turn a **two-column research paper PDF** (IEEE/ACM/USENIX style) into a paragraph-correct
Markdown file plus its figures and tables.

> **v1 scope: two-column papers only**, IEEE, ACM and USENIX styles. The script still
> contains a per-page one-column fallback and a `--single-column` flag, but that
> path is **not validated** in FReSearch yet. Do not claim single-column
> support; if a single-column paper fails, report it.

| | IEEE style | ACM style |
|---|---|---|
| sections | `IV.` / `A.` | `1` / `3.1`; appendices `A`–`D` |
| abstract | inline `Abstract—` | standalone `Abstract` line |
| table caption | below the table | **above** the table |
| figures | usually column-width | often **full-width**, multi-panel |
| references | usually at the end | can precede appendices |

## When to use

- A new PDF is in `papers/_inbox/` and needs `md/paper.md`.
- An existing `paper.md` is stale (source PDF changed) and must be regenerated.
- Figures or tables are missing/wrong and need a re-crop.
- The user explicitly asks for a Chinese full-text translation (see `paper-ingest`).

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

1. **Text** — PyMuPDF `get_text("dict")` blocks, one block ≈ one paragraph; blocks are
   ordered left column then right column. This is why pypdf is not used: it
   flattens paragraphs and mangles small-caps headings.
2. **Mask figures/tables** — blocks whose centre lies inside a figure crop or a
   detected table are dropped, so axis labels do not leak into prose.
3. **Figures** — for each `Fig. N:` caption, crop the region above the caption:
   vector drawing rects plus bitmap panels. A caption spanning both columns means
   a **full-width** figure (crop the full text width). Bitmap panels define the
   area when present; otherwise the densest drawing cluster is used, so a table
   sitting above the figure is not swallowed.
4. **Tables** — `page.find_tables()`, paired with a `TABLE n:` caption **above
   or below** the table. Merged-header tables that cannot be extracted reliably
   are masked and replaced by a caption + placeholder line (never silently
   dropped).
5. **Polish** — merge same-y lines (a heading can be `3` + `Baseline` on two
   baselines), peel headings merged into paragraphs, escape a leading `#` in
   prose, split references on `[n]`, de-hyphenate soft line breaks (inside a
   block, across blocks, and across columns) using the document's own
   vocabulary, and strip `0x00/0x01` control bytes left by math glyphs.

## Two-column layout rules

- Two- vs one-column is decided **per page**, never globally.
- Within a page, blocks sort by `(column, y)`. Sorting by `y` alone interleaves
  the columns and corrupts every paragraph.
- Figure crops are **per column**, bounded below by the previous caption in that
  column. If the caption spans both columns, the figure is full-width and the
  crop uses the whole text width.
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

# 5. no control bytes (would make the file "binary" to grep)
"$PY" -c "d=open('paper.md','rb').read();print([hex(b) for b in d if b<9 or 13<b<32])"

# 6. complex tables are placeholders, not silent drops
grep -n '^> Table' paper.md
```

Pass criteria: no `missing`, figure count == `figures.json` length == captions,
table count matches the PDF, headings non-empty and in section order, no leaked
header lines. If any check fails, report the failure; do not silently accept.

Reference runs:

| Paper | pages | figures | tables | headings |
|---|---|---|---|---|
| Affinity-Model (INFOCOM 2025), IEEE | 10 | 7 | 7 (all extracted) | 20 |
| BEAM (USENIX Security 2024), ACM-like | 18 | 11 (3 full-width) | 3 (1 extracted, 2 placeholders) | 29 |
| Ares (USENIX Security 2025) | 20 | 9 | 16 (5 extracted, 11 placeholders) | 28 |

Use these numbers to spot regressions.

## Gotchas (hard-won; read before editing the script)

- **Vector vs bitmap**: for many vector figures `get_image_info()` finds almost
  nothing; `get_drawings()` is what works. Bitmap panels need both.
- **`Fig. N:` vs `Fig. X.Y`**: accept both numbering styles.
- **Small-caps headings**: pypdf turns `INTRODUCTION` into `I NTRODUCTION`; use
  PyMuPDF blocks instead.
- **Merged headings**: `V. EVALUATION` and `A. Overview` sometimes share a block
  with the next paragraph; peel leading heading lines.
- **`#` in prose**: `#hits / #d2a` must be escaped or it becomes an H1.
- **De-hyphenation**: build the vocabulary **after** normalizing `-\n`; building
  it from raw text makes fragments (`evolu`, `deci`) look like real words and
  keeps every soft hyphen.
- **References across pages**: keep the reference-mode flag at document scope.
  Resetting it per page turns `K. Claffy, ...` into a heading and mangles refs.
- **Subsection letters are roman numerals too**: `### C. Evaluation` must be
  parsed as subsection `C`, not as a roman-numbered section. Match `##` for
  roman sections and `###` for letters.
- **A table above a figure** can sit inside the figure's drawing union. Bound the
  crop with the table's bottom rule (and prefer bitmap clusters), or the table
  disappears into the figure.
- **Merged table headers** (ACM `Table 3`) are not reliably recoverable with
  `find_tables`; emit a placeholder with the page number instead of garbage rows.

## Optional: translate English Markdown → Chinese Markdown

Only when the user explicitly asks; the default pipeline never translates.
Use the chunked workflow owned by `paper-ingest`:

```bash
"$PY" "$ROOT/scripts/translate.py" prepare "$ROOT/papers/$SLUG"
# translate every zh/chunks/NNNN.md -> NNNN.zh.md
"$PY" "$ROOT/scripts/translate.py" assemble "$ROOT/papers/$SLUG" --strict
```

- Output: `zh/paper.zh.md` plus `zh/translation-report.json`.
- Translate chunk by chunk; do not rewrite the whole file at once.
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
- Merged-header/full-width tables may be placeholders; read them from the PDF.
- A soft hyphen broken by an inserted figure or footnote stays at a paragraph
  end (e.g. `differ-` … figure … `ence`); not merged to avoid reordering text.
- Appendix headings in the `D  Title` form are supported; other bespoke heading
  styles may stay as paragraphs.
- Scanned PDFs are refused, not OCR'd.
- A bad path or corrupt PDF exits non-zero with a traceback; capture the message
  and report it, do not retry blindly.
- Soft hyphenation is heuristic: rare cases keep a hyphen (e.g. `Inter-net`).
  Known edge case, still open.
