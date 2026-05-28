#!/usr/bin/env bash
# =============================================================================
# seed-go2rtc-config.sh — Bootstrap go2rtc.yaml from the template
# =============================================================================
# go2rtc rewrites its config file at runtime (persisting discovered streams).
# The file must exist before `docker compose up` because the service bind-
# mounts ./go2rtc.yaml:/config/go2rtc.yaml.
#
# This script copies go2rtc.yaml.template → go2rtc.yaml ONLY if the file
# does not already exist, so a running deployment's learned streams are never
# wiped on `make up`.
#
# Usage (standalone):  bash scripts/seed-go2rtc-config.sh
# Usage (Makefile):    called automatically by `make up` and `make dev`
# Usage (install.sh):  called once during first-install
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE="$REPO_ROOT/go2rtc.yaml.template"
TARGET="$REPO_ROOT/go2rtc.yaml"

if [[ ! -f "$TEMPLATE" ]]; then
    echo "[seed-go2rtc] ERROR: template not found at $TEMPLATE" >&2
    exit 1
fi

if [[ -f "$TARGET" ]]; then
    echo "[seed-go2rtc] go2rtc.yaml already exists — skipping seed"
    exit 0
fi

cp "$TEMPLATE" "$TARGET"
echo "[seed-go2rtc] go2rtc.yaml seeded from template"
