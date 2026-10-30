#!/usr/bin/env python3
"""Verify the FReSearch runtime: repo layout, Python version, pinned dependencies.

Stdlib only, so it can be run before the venv exists:
    python3 scripts/check_env.py          # human readable
    python3 scripts/check_env.py --json   # machine readable
    python3 scripts/check_env.py --quiet  # exit code only

Exit code: 0 = no failures (warnings allowed), 1 = at least one failure.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from importlib import metadata
from pathlib import Path

MIN_PY = (3, 10)
TARGET_PY = (3, 12)
REQUIRED_DIRS = ("papers", "papers/_inbox", "skills", "specs", "scripts", "index")
# requirement name -> import name (they differ only by case here)
IMPORT_NAMES = {"pymupdf": "pymupdf", "pypdf": "pypdf"}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def parse_pins(path: Path) -> list[tuple[str, str | None]]:
    pins: list[tuple[str, str | None]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*==\s*([^\s;]+)", line)
        if m:
            pins.append((m.group(1), m.group(2)))
        else:
            pins.append((line, None))
    return pins


def add(results: list[dict], name: str, status: str, detail: str) -> None:
    results.append({"check": name, "status": status, "detail": detail})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quiet", action="store_true", help="only print on failure")
    args = ap.parse_args()

    root = repo_root()
    results: list[dict] = []

    # Python version
    have = sys.version_info[:2]
    if have < MIN_PY:
        add(results, "python", "FAIL", f"{have[0]}.{have[1]} < required {MIN_PY[0]}.{MIN_PY[1]}")
    elif have != TARGET_PY:
        add(results, "python", "WARN", f"{have[0]}.{have[1]} (target {TARGET_PY[0]}.{TARGET_PY[1]})")
    else:
        add(results, "python", "OK", f"{have[0]}.{have[1]}")

    # venv
    in_venv = sys.prefix != sys.base_prefix
    venv = root / ".venv"
    if in_venv:
        add(results, "venv", "OK", sys.prefix)
    elif (venv / "bin" / "python").exists():
        add(results, "venv", "WARN", f"not in venv; use {venv / 'bin' / 'python'}")
    else:
        add(results, "venv", "FAIL", "no .venv; run: bash scripts/bootstrap_env.sh")

    # layout
    missing = [d for d in REQUIRED_DIRS if not (root / d).is_dir()]
    if missing:
        add(results, "layout", "FAIL", "missing: " + ", ".join(missing))
    else:
        add(results, "layout", "OK", str(root))

    # dependencies
    req = root / "requirements.txt"
    if not req.exists():
        add(results, "requirements", "FAIL", "requirements.txt not found")
    else:
        pins = parse_pins(req)
        add(results, "requirements", "OK", f"{len(pins)} pinned")
        for name, pin in pins:
            try:
                installed = metadata.version(name)
            except metadata.PackageNotFoundError:
                add(results, f"dep:{name}", "FAIL", "not installed; run: bash scripts/bootstrap_env.sh")
                continue
            if pin and installed != pin:
                add(results, f"dep:{name}", "FAIL", f"installed {installed} != pinned {pin}")
            else:
                add(results, f"dep:{name}", "OK", installed)
            modname = IMPORT_NAMES.get(name.lower(), name.lower().replace("-", "_"))
            try:
                importlib.import_module(modname)
            except Exception as exc:  # noqa: BLE001 - report any import failure
                add(results, f"import:{modname}", "FAIL", f"{type(exc).__name__}: {exc}")

    # writable inbox
    inbox = root / "papers" / "_inbox"
    if inbox.is_dir():
        writable = os.access(inbox, os.W_OK)
        add(results, "inbox", "OK" if writable else "WARN",
            str(inbox) + ("" if writable else " (not writable)"))
    else:
        add(results, "inbox", "FAIL", "papers/_inbox missing")

    failures = [r for r in results if r["status"] == "FAIL"]
    warnings = [r for r in results if r["status"] == "WARN"]

    if args.json:
        print(json.dumps({"ok": not failures, "root": str(root),
                          "python": sys.version.split()[0], "checks": results}, indent=2))
    elif not args.quiet or failures:
        for r in results:
            if args.quiet and r["status"] == "OK":
                continue
            print(f"[{r['status']:<4}] {r['check']:<18} {r['detail']}")
        print(f"\n{len(results) - len(failures) - len(warnings)} OK, "
              f"{len(warnings)} WARN, {len(failures)} FAIL")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
