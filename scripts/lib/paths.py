"""Canonical paths inside the FReSearch repository."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAPERS = ROOT / "papers"
INBOX = PAPERS / "_inbox"
INDEX = ROOT / "index"


def paper_dir(slug: str) -> Path:
    return PAPERS / slug


def source_pdf(slug: str) -> Path:
    return paper_dir(slug) / "source" / "paper.pdf"


def md_path(slug: str) -> Path:
    return paper_dir(slug) / "md" / "paper.md"


def digest_dir(slug: str) -> Path:
    return paper_dir(slug) / "digest"


def digest_json(slug: str) -> Path:
    return digest_dir(slug) / "digest.json"


def digest_md(slug: str) -> Path:
    return digest_dir(slug) / "digest.zh.md"


def translation_md(slug: str) -> Path:
    return paper_dir(slug) / "zh" / "paper.zh.md"


def meta_path(slug: str) -> Path:
    return paper_dir(slug) / "meta.json"
