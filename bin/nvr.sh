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
#
# AI plugins (marketplace): set AI_PLUGINS to the scenarios to run, e.g.
#   AI_PLUGINS="frs ppe" bin/nvr.sh up
# Each plugin is its own compose overlay (docker-compose.<slug>.yml). When
# AI_PLUGINS is set, the shared AI infra overlay (ai-base: triton/qdrant/rustfs)
# is included automatically. Unset/empty = NVR core only (no AI).
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE="docker compose -f $REPO_ROOT/docker-compose.yml"

# Compose the AI overlay set from AI_PLUGINS (space/comma separated scenario
# slugs). One overlay file per plugin keeps install/uninstall granular: a plugin
# the operator hasn't licensed simply isn't in the list, so its containers never
# start. ai-base is added once, only when at least one plugin is requested.
AI_PLUGINS="${AI_PLUGINS:-}"
if [[ -n "${AI_PLUGINS// /}" ]]; then
  COMPOSE="$COMPOSE -f $REPO_ROOT/docker-compose.ai-base.yml"
  for _p in ${AI_PLUGINS//,/ }; do
    _f="$REPO_ROOT/docker-compose.${_p}.yml"
    if [[ -f "$_f" ]]; then
      COMPOSE="$COMPOSE -f $_f"
    else
      echo "warn: AI plugin '$_p' has no overlay ($_f) — skipping" >&2
    fi
  done
fi

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
    $COMPOSE run --rm migrate
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
