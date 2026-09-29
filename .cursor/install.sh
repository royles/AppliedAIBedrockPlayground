#!/usr/bin/env bash
# Idempotent bootstrap for Bedrock Playground (Cloud Agent / local).
set -euo pipefail

cd "$(dirname "$0")/.."

if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  echo "Installing python3-venv..."
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends python3-venv
fi

if [[ ! -d backend/venv ]]; then
  python3 -m venv backend/venv
fi

# shellcheck disable=SC1091
. backend/venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [[ ! -f frontend/dist/index.html ]] && command -v npm >/dev/null 2>&1; then
  echo "Building frontend (dist missing)..."
  npm ci --prefix frontend
  npm run build --prefix frontend
fi

echo "Install complete."
