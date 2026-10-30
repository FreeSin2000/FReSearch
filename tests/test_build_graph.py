"""Unit tests for scripts/build_graph.py (stdlib unittest)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_graph as bg  # noqa: E402


def digest(slug: str, keywords: list[str], datasets: list[str],
           metrics: list[str] | None = None, methods: list[str] | None = None) -> dict:
    return {
        "_slug": slug,
        "title": {"en": slug},
        "keywords": [{"zh": k, "en": k} for k in keywords],
        "data": [{"name": d, "scale": "", "source": ""} for d in datasets],
        "metrics": metrics or [],
        "method": [{"name": m, "role": "", "detail": ""} for m in (methods or [])],
        "relations": {},
    }


class TestNormalize(unittest.TestCase):
    def test_norm(self) -> None:
        self.assertEqual(bg.norm("Route Views"), "route views")
        self.assertEqual(bg.norm("RouteViews"), "routeviews")
        self.assertEqual(bg.norm("BGP-Hijacking!"), "bgp hijacking")


class TestDerived(unittest.TestCase):
    def test_comparable_needs_two_keywords_and_dataset(self) -> None:
        a = digest("a", ["BGP", "routing", "x"], ["Route Views"])
        b = digest("b", ["BGP", "routing", "y"], ["RouteViews"])
        edges = bg.derived_edges({"a": a, "b": b})
        kinds = [e["type"] for e in edges]
        self.assertIn("comparable_with", kinds)
        self.assertIn("same_dataset", kinds)
        comp = next(e for e in edges if e["type"] == "comparable_with")
        self.assertEqual(comp["from"], "paper:a")
        self.assertEqual(comp["to"], "paper:b")
        self.assertEqual(comp["confidence"], "derived")
        self.assertTrue(any(m.startswith("dataset:") for m in comp["matched_on"]))

    def test_one_keyword_is_not_enough(self) -> None:
        a = digest("a", ["BGP", "routing"], ["Route Views"])
        b = digest("b", ["BGP", "anomaly"], ["Route Views"])
        edges = bg.derived_edges({"a": a, "b": b})
        self.assertNotIn("comparable_with", [e["type"] for e in edges])
        self.assertIn("same_dataset", [e["type"] for e in edges])

    def test_symmetric_order(self) -> None:
        a = digest("zzz", ["BGP", "routing"], ["Route Views"])
        b = digest("aaa", ["BGP", "routing"], ["Route Views"])
        edges = bg.derived_edges({"zzz": a, "aaa": b})
        comp = next(e for e in edges if e["type"] == "comparable_with")
        self.assertEqual((comp["from"], comp["to"]), ("paper:aaa", "paper:zzz"))

    def test_same_method(self) -> None:
        a = digest("a", ["BGP", "routing"], ["D"], methods=["XGBoost"])
        b = digest("b", ["BGP", "routing"], ["D"], methods=["xgboost"])
        edges = bg.derived_edges({"a": a, "b": b})
        self.assertIn("same_method", [e["type"] for e in edges])


class TestDedupe(unittest.TestCase):
    def test_explicit_wins(self) -> None:
        derived = {"from": "paper:a", "type": "same_dataset", "to": "paper:b",
                   "evidence": "derived", "confidence": "derived", "matched_on": ["dataset:D"]}
        explicit = {"from": "paper:a", "type": "same_dataset", "to": "paper:b",
                    "evidence": "§5.1", "confidence": "explicit"}
        out = bg.dedupe([derived, explicit])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["confidence"], "explicit")


if __name__ == "__main__":
    unittest.main()
