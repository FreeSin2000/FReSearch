#!/usr/bin/env bash
# Create or verify the FReSearch Python environment.
#
#   bash scripts/bootstrap_env.sh          # idempotent: reuse if complete, else create/repair
#   bash scripts/bootstrap_env.sh --check  # verify only, never install
#   bash scripts/bootstrap_env.sh --force  # delete .venv and rebuild from requirements.txt
#
# The venv lives at <repo>/.venv and is gitignored. Pinned versions come from
# requirements.txt; a new session only needs to re-run this script once.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
REQ="$ROOT/requirements.txt"
UV="${UV:-uv}"

FORCE=0
CHECK=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --check) CHECK=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "bootstrap_env: unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$REQ" ]]; then
  echo "bootstrap_env: missing $REQ" >&2
  exit 1
fi

if [[ "$FORCE" -eq 1 ]]; then
  echo "[env] --force: removing $VENV"
  rm -rf "$VENV"
fi

if [[ "$CHECK" -eq 1 ]]; then
  if [[ -x "$PY" ]]; then
    exec "$PY" "$ROOT/scripts/check_env.py"
  fi
  echo "[env] no venv at $VENV" >&2
  exit 1
fi

# Fast path: an existing venv that already matches requirements is left untouched.
if [[ -x "$PY" ]]; then
  if "$PY" "$ROOT/scripts/check_env.py" --quiet; then
    echo "[env] reuse $VENV"
    exit 0
  fi
  echo "[env] existing venv incomplete; repairing from requirements.txt"
fi

if ! command -v "$UV" >/dev/null 2>&1; then
  echo "[env] uv not found. Install it first: https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [[ ! -x "$PY" ]]; then
  echo "[env] creating $VENV"
  # Prefer the pinned target interpreter; fall back to uv's default.
  "$UV" venv --python 3.12 "$VENV" 2>/dev/null || "$UV" venv "$VENV"
fi

COUNT=$(grep -c -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$REQ")
echo "[env] installing $COUNT pinned packages"
"$UV" pip install --python "$PY" -r "$REQ"

exec "$PY" "$ROOT/scripts/check_env.py"
