"""Unit tests for scripts/ingest.py helpers (stdlib unittest)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ingest  # noqa: E402


class TestSlug(unittest.TestCase):
    def test_short_title_uses_prefix_before_colon(self) -> None:
        self.assertEqual(
            ingest.short_title("Affinity-Model: Improving AS Routing Models via AS Affinity"),
            "affinity-model")

    def test_short_title_drops_stopwords(self) -> None:
        self.assertEqual(
            ingest.short_title("Learning with Semantics: Towards a Semantics-Aware System"),
            "learning-semantics")

    def test_short_title_fallback(self) -> None:
        self.assertEqual(ingest.short_title("The of and"), "the-of-and")

    def test_kebab(self) -> None:
        self.assertEqual(ingest.kebab("USENIX Security 2024"), "usenix-security-2024")


class TestVenue(unittest.TestCase):
    def test_infocom(self) -> None:
        self.assertEqual(
            ingest.detect_venue("IEEE INFOCOM 2025 - IEEE Conference on Computer Communications"),
            ("infocom", 2025))

    def test_usenix(self) -> None:
        self.assertEqual(ingest.detect_venue("33rd USENIX Security Symposium"), ("usenixsecurity", None))

    def test_unknown(self) -> None:
        self.assertEqual(ingest.detect_venue("Some random text without a venue"), (None, None))

    def test_priority_usenix_over_imc(self) -> None:
        text = "USENIX Security 2024 and IMC 2024"
        self.assertEqual(ingest.detect_venue(text)[0], "usenixsecurity")


if __name__ == "__main__":
    unittest.main()
