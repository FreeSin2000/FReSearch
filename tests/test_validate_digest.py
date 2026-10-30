"""Unit tests for scripts/validate_digest.py (stdlib unittest)."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_digest as vd  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "valid"
SLUG = "infocom2025-affinity-model"


def load_json() -> dict:
    return json.loads((FIX / "digest.json").read_text(encoding="utf-8"))


def load_md() -> str:
    return (FIX / "digest.zh.md").read_text(encoding="utf-8")


def load_paper() -> str:
    return (FIX / "paper.md").read_text(encoding="utf-8")


def messages(report: vd.Report, level: str = "error") -> str:
    return " | ".join(p.msg for p in report.problems if p.level == level)


class TestDigestJson(unittest.TestCase):
    def test_valid(self) -> None:
        rep = vd.validate_digest_object(load_json(), slug=SLUG, paper_md=load_paper())
        self.assertEqual(rep.errors, [], messages(rep))

    def test_missing_field(self) -> None:
        obj = load_json()
        del obj["gap"]
        rep = vd.validate_digest_object(obj)
        self.assertIn("missing required field: gap", messages(rep))

    def test_empty_evidence(self) -> None:
        obj = load_json()
        obj["headline_results"][0]["evidence"] = ""
        rep = vd.validate_digest_object(obj)
        self.assertIn("missing evidence", messages(rep))

    def test_bad_relation_target(self) -> None:
        obj = load_json()
        obj["relations"]["builds_on"][0]["target"] = "gao2000"
        rep = vd.validate_digest_object(obj)
        self.assertIn("must be paper:<slug>", messages(rep))

    def test_explicit_cannot_be_unverified(self) -> None:
        obj = load_json()
        obj["relations"]["builds_on"][0]["evidence"] = "unverified"
        rep = vd.validate_digest_object(obj)
        self.assertIn("unverified evidence not allowed", messages(rep))

    def test_derived_edge_needs_matched_on(self) -> None:
        obj = load_json()
        obj["relations"]["contradicts"] = [{
            "target": "ext:foo2024:bar",
            "evidence": "derived",
            "confidence": "derived",
        }]
        rep = vd.validate_digest_object(obj)
        self.assertIn("derived edge needs matched_on", messages(rep))

    def test_number_not_in_paper(self) -> None:
        obj = load_json()
        obj["headline_results"][0]["value"] = "99.9%"
        rep = vd.validate_digest_object(obj, paper_md=load_paper())
        self.assertIn("number not found in paper.md: 99.9%", messages(rep))

    def test_missing_anchor_in_paper(self) -> None:
        obj = load_json()
        obj["headline_results"][1]["evidence"] = "§IX"
        rep = vd.validate_digest_object(obj, paper_md=load_paper())
        self.assertIn("section anchor not found", messages(rep))

    def test_slug_mismatch(self) -> None:
        rep = vd.validate_digest_object(load_json(), slug="wrong-slug")
        self.assertIn("!= directory slug", messages(rep))


class TestDigestMarkdown(unittest.TestCase):
    def test_valid_structure(self) -> None:
        rep = vd.validate_digest_md(load_md())
        self.assertEqual(rep.errors, [], messages(rep))

    def test_missing_l2(self) -> None:
        text = load_md().split("## L2 详细总结")[0]
        rep = vd.validate_digest_md(text)
        self.assertIn("section missing", messages(rep))

    def test_missing_l3(self) -> None:
        text = load_md().split("## L3 深度剖析")[0]
        rep = vd.validate_digest_md(text)
        self.assertIn("section missing", messages(rep))

    def test_short_l2_is_warning(self) -> None:
        rep = vd.validate_digest_md(load_md())
        self.assertTrue(any(p.where == "L2 详细总结" and "outside" in p.msg
                            for p in rep.warnings))

    def test_non_chinese_l0(self) -> None:
        text = load_md().replace(
            "AM 用路径推断发现被传统模型忽略的 AS 亲和行为，将真实路由行为覆盖率提升到 85.9%。",
            "Affinity-Model infers affinity behavior and reaches 85.9% coverage.")
        rep = vd.validate_digest_md(text)
        self.assertIn("no Chinese text", messages(rep))


class TestCli(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_digest.py"), *args],
            capture_output=True, text=True, cwd=ROOT,
        )

    def test_valid_exit_zero(self) -> None:
        r = self.run_cli(str(FIX / "digest.json"), "--paper-md", str(FIX / "paper.md"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_invalid_exit_one(self) -> None:
        obj = load_json()
        del obj["title"]
        tmp = ROOT / "tests" / "_tmp_bad.json"
        tmp.write_text(json.dumps(obj), encoding="utf-8")
        try:
            r = self.run_cli(str(tmp))
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("missing required field: title", r.stdout)
        finally:
            tmp.unlink(missing_ok=True)

    def test_json_output(self) -> None:
        r = self.run_cli(str(FIX / "digest.json"), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["errors"], 0)


if __name__ == "__main__":
    unittest.main()
