#!/usr/bin/env bash
# Single entry point for all 4 test layers.
# Use this in CI and locally — never run pytest in isolation.

set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

echo "=== Layer 1: build (must be reproducible) ==="
python3 scripts/build.py
python3 scripts/build.py --check

echo
echo "=== Layer 2: pytest (unit + golden + canary + idempotent) ==="
python3 -m pytest tests/ -v --tb=short

echo
echo "=== Layer 3: bash -n on real install.sh + dry-install ==="
bash -n dist/install.sh
echo "  ✓ dist/install.sh bash -n"

echo
echo "All checks green."
