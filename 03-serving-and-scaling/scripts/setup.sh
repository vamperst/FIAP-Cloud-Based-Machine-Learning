#!/usr/bin/env bash
# Creates/updates the .venv for this lab. Idempotent: safe to run twice.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v terraform >/dev/null 2>&1; then
  echo "==> terraform not found on PATH. Install it via the course's standard mechanism before continuing." >&2
  exit 1
fi
echo "==> terraform $(terraform version -json | python3 -c 'import json,sys; print(json.load(sys.stdin)["terraform_version"])' 2>/dev/null || terraform version | head -1) available"

if [ ! -x .venv/bin/python ]; then
  echo "==> creating .venv"
  python3 -m venv .venv
fi

.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> terraform : $(terraform version | head -1)"
echo "==> python    : $(.venv/bin/python --version)"
echo "==> pronto. Próximo passo: make doctor"
