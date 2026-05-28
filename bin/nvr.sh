#!/usr/bin/env bash
# =============================================================================
# nvr — cross-platform NVR stack manager (bash edition)
# =============================================================================
# Usage:
#   bin/nvr.sh up          — seed go2rtc config + docker compose up -d
#   bin/nvr.sh down        — docker compose down
#   bin/nvr.sh logs [svc]  — follow logs (default: backend)
#   bin/nvr.sh rebuild     — rebuild images + bring up
#   bin/nvr.sh migrate     — run alembic upgrade head
#   bin/nvr.sh ps          — show container status
#   bin/nvr.sh restart     — restart all services
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE="docker compose -f $REPO_ROOT/docker-compose.yml"

cmd="${1:-help}"
shift || true

case "$cmd" in
  up)
    bash "$REPO_ROOT/scripts/seed-go2rtc-config.sh"
    $COMPOSE up -d "$@"
    ;;

  down)
    $COMPOSE down "$@"
    ;;

  logs)
    svc="${1:-backend}"
    shift || true
    $COMPOSE logs -f "$svc" "$@"
    ;;

  rebuild)
    $COMPOSE build
    $COMPOSE up -d "$@"
    ;;

  migrate)
    $COMPOSE run --rm migrate alembic upgrade head
    ;;

  ps)
    $COMPOSE ps "$@"
    ;;

  restart)
    $COMPOSE restart "$@"
    ;;

  help|--help|-h)
    cat <<'EOF'
nvr — GVD NVR stack manager

Commands:
  up              Seed go2rtc config and start the full stack
  down            Stop all services
  logs [service]  Tail logs (default: backend)
  rebuild         Rebuild images and restart
  migrate         Apply database migrations
  ps              Show container status
  restart         Restart all services

Examples:
  bin/nvr.sh up
  bin/nvr.sh logs nginx
  bin/nvr.sh rebuild
EOF
    ;;

  *)
    echo "Unknown command: $cmd" >&2
    echo "Run: bin/nvr.sh help" >&2
    exit 1
    ;;
esac
