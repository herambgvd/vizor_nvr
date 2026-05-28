#!/usr/bin/env bash
# =============================================================================
# GVD NVR — uninstall script
# =============================================================================
# Removes containers, volumes, systemd unit, and host data.
# Usage:
#   sudo ./scripts/uninstall.sh           # interactive
#   sudo ./scripts/uninstall.sh --force   # non-interactive
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

log()   { printf '\033[1;34m[uninstall]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
fatal() { printf '\033[1;31m[error]\033[0m %s\n' "$*"; exit 1; }

if [[ $FORCE -eq 0 ]]; then
    echo "This will remove the GVD NVR stack, including:"
    echo "  - All running Docker containers"
    echo "  - Docker volumes (db_data, recordings, thumbnails, exports, certs, hls)"
    echo "  - The systemd service (gvd-nvr.service)"
    echo "  - Host storage path data (if configured)"
    echo
    read -rp "Are you sure? Type 'yes' to continue: " confirm
    [[ "$confirm" == "yes" ]] || fatal "Aborted."
fi

# Stop and remove containers + volumes
log "Stopping and removing containers..."
if [[ -f "$REPO_ROOT/docker-compose.yml" ]]; then
    docker compose -f "$REPO_ROOT/docker-compose.yml" down -v 2>/dev/null || true
fi

# Remove systemd unit
UNIT_PATH=/etc/systemd/system/gvd-nvr.service
if [[ -f "$UNIT_PATH" ]]; then
    log "Removing systemd unit..."
    systemctl stop gvd-nvr.service 2>/dev/null || true
    systemctl disable gvd-nvr.service 2>/dev/null || true
    rm -f "$UNIT_PATH"
    systemctl daemon-reload
fi

# Remove host storage (optional)
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
    STORAGE_HOST_PATH=$(grep '^STORAGE_HOST_PATH=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
    if [[ -n "${STORAGE_HOST_PATH:-}" && -d "$STORAGE_HOST_PATH" && $FORCE -eq 0 ]]; then
        echo
        read -rp "Remove host storage at $STORAGE_HOST_PATH? Type 'yes': " rm_storage
        if [[ "$rm_storage" == "yes" ]]; then
            log "Removing $STORAGE_HOST_PATH ..."
            rm -rf "$STORAGE_HOST_PATH"
        else
            warn "Host storage preserved at $STORAGE_HOST_PATH"
        fi
    fi
fi

log "Uninstall complete."
