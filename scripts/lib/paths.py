"""Canonical paths inside the FReSearch repository."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAPERS = ROOT / "papers"
INBOX = PAPERS / "_inbox"
INDEX = ROOT / "index"
