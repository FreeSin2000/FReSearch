"""Unit tests for scripts/translate.py (stdlib unittest)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import translate  # noqa: E402

FIXTURE_MD = ROOT / "tests" / "fixtures" / "valid" / "paper.md"


class TestChunking(unittest.TestCase):
    def setUp(self) -> None:
        self.text = FIXTURE_MD.read_text(encoding="utf-8")

    def test_split_sections_keeps_all_text(self) -> None:
        sections = translate.split_sections(self.text)
        self.assertGreater(len(sections), 1)
        self.assertEqual("".join(sections).strip(), self.text.strip())

    def test_chunks_preserve_counts(self) -> None:
        chunks = translate.chunk_sections(translate.split_sections(self.text), 600)
        self.assertGreater(len(chunks), 1)
        total = translate.counts(self.text)
        got = {k: sum(translate.counts(c)[k] for c in chunks)
               for k in ("headings", "table_rows", "images")}
        for k, v in got.items():
            self.assertEqual(v, total[k], k)

    def test_no_chunk_is_empty(self) -> None:
        for c in translate.chunk_sections(translate.split_sections(self.text), 600):
            self.assertTrue(c.strip())


class TestPrepareAssemble(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "md").mkdir()
        shutil.copy(FIXTURE_MD, self.tmp / "md" / "paper.md")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_roundtrip_identity(self) -> None:
        self.assertEqual(translate.prepare(self.tmp, 600, False), 0)
        manifest = json.loads((self.tmp / "zh" / "manifest.json").read_text())
        for ch in manifest["chunks"]:
            src = self.tmp / "zh" / ch["file"]
            (self.tmp / "zh" / f"chunks/{ch['id']}.zh.md").write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(translate.assemble(self.tmp, False), 0)
        self.assertTrue((self.tmp / "zh" / "paper.zh.md").exists())

    def test_missing_chunk_fails(self) -> None:
        translate.prepare(self.tmp, 600, False)
        self.assertEqual(translate.assemble(self.tmp, False), 1)


if __name__ == "__main__":
    unittest.main()
