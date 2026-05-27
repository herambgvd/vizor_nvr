#!/usr/bin/env sh
# =============================================================================
# Backend entrypoint
# =============================================================================
# Runs as root just long enough to fix /data ownership (volumes mount as
# root by default), then drops privileges to the `nvr` user and execs
# uvicorn. License grace file, TLS bootstrap, and snapshot caches all
# need /data writable by uid 1001.
#
# Migrations are NOT run here. The dedicated `migrate` one-shot service
# (backend depends_on: migrate: service_completed_successfully) owns
# schema upgrades; running them in both places caused a race that left
# both containers in a restart loop.
# =============================================================================

set -e

if [ "$(id -u)" = "0" ]; then
  mkdir -p /data /data/recordings /data/thumbnails /data/exports /data/hls /data/certs
  chown -R 1001:1001 /data
  exec su -s /bin/sh nvr -c "exec $*"
fi

exec "$@"
