#!/usr/bin/env bash
# Regenerate packaging/Ledger.icns from packaging/icon.png (draws a default icon if missing).
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f packaging/icon.png ]] || uv run python packaging/make_icon.py
set=$(mktemp -d)/Ledger.iconset
mkdir -p "$set"
for s in 16 32 128 256 512; do
  sips -z $s $s packaging/icon.png --out "$set/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) packaging/icon.png --out "$set/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$set" -o packaging/Ledger.icns
echo "Wrote packaging/Ledger.icns"
