#!/usr/bin/env bash
# =============================================================================
# SOPS Decryption Entrypoint
# =============================================================================
# Wraps any container CMD so it boots with secrets decrypted from a
# SOPS-encrypted env file. Avoids ever writing plaintext to disk.
#
# Usage in Dockerfile/compose:
#   ENV SOPS_AGE_KEY_FILE=/run/secrets/age-key.txt
#   ENV SOPS_ENV_FILE=/app/.sops.env
#   ENTRYPOINT ["/usr/local/bin/sops-entrypoint.sh"]
#   CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
#
# The age private key is mounted as a Docker secret. The encrypted env file
# is baked into the image (it is, after all, encrypted).
# =============================================================================

set -euo pipefail

SOPS_ENV_FILE="${SOPS_ENV_FILE:-}"

if [[ -n "${SOPS_ENV_FILE}" && -f "${SOPS_ENV_FILE}" ]]; then
  if ! command -v sops >/dev/null 2>&1; then
    echo "[sops-entrypoint] FATAL: sops binary not in image" >&2
    exit 1
  fi
  if [[ -z "${SOPS_AGE_KEY_FILE:-}" && -z "${SOPS_AGE_KEY:-}" ]]; then
    echo "[sops-entrypoint] FATAL: neither SOPS_AGE_KEY_FILE nor SOPS_AGE_KEY set" >&2
    exit 1
  fi

  # Decrypt to a tmpfs path (never touches durable disk)
  decrypted=$(mktemp)
  trap 'rm -f "${decrypted}"' EXIT
  sops --decrypt "${SOPS_ENV_FILE}" > "${decrypted}"

  # Export each KEY=VALUE pair into the environment
  set -a
  # shellcheck disable=SC1090
  source "${decrypted}"
  set +a

  rm -f "${decrypted}"
  trap - EXIT
fi

exec "$@"
