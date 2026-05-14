#!/usr/bin/env bash
# =============================================================================
# SOPS Bootstrap — install age + SOPS, generate operator key, encrypt secrets
# =============================================================================
# Run this once on a new operator machine. Idempotent.
#
# Outputs:
#   ~/.config/sops/age/keys.txt     — your private age key (BACK UP THIS FILE)
#   prints your public key to stdout — paste into .sops.yaml creation_rules
#
# Usage:
#   bash scripts/sops-bootstrap.sh install        # install age + sops binaries
#   bash scripts/sops-bootstrap.sh keygen         # generate age key
#   bash scripts/sops-bootstrap.sh encrypt PATH   # encrypt a plaintext env file
#   bash scripts/sops-bootstrap.sh decrypt PATH   # decrypt to stdout (for runtime)
#   bash scripts/sops-bootstrap.sh edit PATH      # edit encrypted file in $EDITOR
# =============================================================================

set -euo pipefail

KEY_DIR="${HOME}/.config/sops/age"
KEY_FILE="${KEY_DIR}/keys.txt"

cmd_install() {
  if command -v age >/dev/null 2>&1 && command -v sops >/dev/null 2>&1; then
    echo "age and sops already installed"
    return
  fi

  echo "Installing age and sops..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y age
    # SOPS not in default apt; download from GitHub releases
    local sops_ver="3.9.4"
    local arch="amd64"
    [[ "$(uname -m)" == "aarch64" ]] && arch="arm64"
    sudo curl -fsSL \
      "https://github.com/getsops/sops/releases/download/v${sops_ver}/sops-v${sops_ver}.linux.${arch}" \
      -o /usr/local/bin/sops
    sudo chmod +x /usr/local/bin/sops
  elif command -v brew >/dev/null 2>&1; then
    brew install age sops
  else
    echo "Unsupported platform. Install age + sops manually." >&2
    exit 1
  fi
  echo "Installed: $(age --version) ; $(sops --version)"
}

cmd_keygen() {
  if [[ -f "${KEY_FILE}" ]]; then
    echo "Key already exists at ${KEY_FILE}" >&2
    echo "Public key:"
    grep -E '^# public key:' "${KEY_FILE}" | head -1 | awk '{print $4}'
    return
  fi

  mkdir -p "${KEY_DIR}"
  age-keygen -o "${KEY_FILE}"
  chmod 600 "${KEY_FILE}"

  echo ""
  echo "Generated ${KEY_FILE}"
  echo ""
  echo "==> BACK UP THIS FILE NOW. If lost, encrypted secrets become unrecoverable."
  echo ""
  echo "Your PUBLIC key (paste into .sops.yaml):"
  grep -E '^# public key:' "${KEY_FILE}" | head -1 | awk '{print $4}'
}

cmd_encrypt() {
  local target="${1:?usage: encrypt PATH}"
  if [[ ! -f "${target}" ]]; then
    echo "File not found: ${target}" >&2
    exit 1
  fi

  # If the target is foo/.env, encrypt to foo/.env.sops
  local encrypted="${target%.env}.sops.env"
  if [[ "${target}" != *.env ]]; then
    encrypted="${target}.sops"
  fi

  sops --encrypt --input-type dotenv --output-type dotenv "${target}" > "${encrypted}"
  echo "Wrote encrypted: ${encrypted}"
  echo ""
  echo "Next: delete the plaintext ${target} and commit ${encrypted}."
}

cmd_decrypt() {
  local target="${1:?usage: decrypt PATH}"
  sops --decrypt "${target}"
}

cmd_edit() {
  local target="${1:?usage: edit PATH}"
  sops "${target}"
}

action="${1:-help}"; shift || true
case "${action}" in
  install) cmd_install ;;
  keygen)  cmd_keygen ;;
  encrypt) cmd_encrypt "$@" ;;
  decrypt) cmd_decrypt "$@" ;;
  edit)    cmd_edit "$@" ;;
  *)
    grep -E '^# ' "$0" | head -25 ;;
esac
