#!/usr/bin/env sh
# =============================================================================
# Backend entrypoint
# =============================================================================
# Runs as root just long enough to fix /data ownership (volumes mount as
# root by default), then drops privileges to the `nvr` user and execs
# uvicorn. License grace file, TLS bootstrap, and snapshot caches all
# need /data writable by uid 1001.
# =============================================================================

set -e

# Ensure the data tree is writable by the nvr user before we drop privs.
# Volumes survive container recreates so this is the cheapest place to
# enforce ownership — it's a no-op when perms are already correct.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data /data/recordings /data/thumbnails /data/exports /data/hls /data/certs
  chown -R 1001:1001 /data
  # Run migrations before launching the app. If the DB isn't reachable
  # yet, fail loudly so the orchestrator (docker compose / k8s) restarts
  # us; the depends_on healthcheck on the db service should make this
  # rare.
  su -s /bin/sh nvr -c "alembic upgrade head"
  exec su -s /bin/sh nvr -c "exec $*"
fi

# Re-entry path (already non-root): same order.
alembic upgrade head
exec "$@"
