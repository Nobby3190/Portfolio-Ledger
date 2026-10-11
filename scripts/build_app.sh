#!/usr/bin/env bash
# Build "dist/帳本 Ledger.app". Pass --install to also copy it into /Applications.
set -euo pipefail
cd "$(dirname "$0")/.."

npm --prefix frontend ci
npm --prefix frontend run build
[[ -f packaging/Ledger.icns ]] || ./scripts/make_icon.sh
uv sync
uv run pyinstaller --noconfirm --clean Ledger.spec

# Ad-hoc signature: enough to run on this Mac (required on Apple Silicon).
codesign --force --deep --sign - "dist/帳本 Ledger.app"
echo "Built dist/帳本 Ledger.app"

if [[ "${1:-}" == "--install" ]]; then
  rm -rf "/Applications/帳本 Ledger.app"
  ditto "dist/帳本 Ledger.app" "/Applications/帳本 Ledger.app"
  echo "Installed to /Applications/帳本 Ledger.app"
fi
