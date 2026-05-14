# Secrets Management — SOPS + age

Vizor uses [SOPS](https://github.com/getsops/sops) with [age](https://github.com/FiloSottile/age) to keep encrypted secrets in the git repo without ever committing plaintext.

## Why

- Plaintext `.env` files leak via screenshots, shell history, backups, container images, CI logs
- SOPS encrypts each value individually so `git diff` still shows which keys changed
- age keys are simpler than GPG (one-line public key, single private key file)
- Multiple operators can decrypt with their own keys — no shared password
- Production secrets stay encrypted on disk; only decrypted in memory at boot

## Quick Start

### 1. Install tools

```bash
bash scripts/sops-bootstrap.sh install
```

### 2. Generate your operator age key

```bash
bash scripts/sops-bootstrap.sh keygen
# Outputs your PUBLIC key — copy it.
# Private key is at ~/.config/sops/age/keys.txt — BACK THIS UP.
```

### 3. Add your public key to `.sops.yaml`

Paste your `age1...` public key into the `creation_rules.age` block. Commit the change.

### 4. Encrypt the project `.env`

```bash
cp backend/.env.example backend/.env
# Edit backend/.env with real values
bash scripts/sops-bootstrap.sh encrypt backend/.env
# Wrote backend/.sops.env

rm backend/.env                       # Delete plaintext immediately
git add backend/.sops.env
git commit -m "secrets: initial encrypted env"
```

### 5. Boot the stack with decryption

Compose mounts the operator's age private key as a Docker secret:

```yaml
secrets:
  age_key:
    file: ~/.config/sops/age/keys.txt

services:
  backend:
    secrets:
      - age_key
    environment:
      SOPS_AGE_KEY_FILE: /run/secrets/age_key
      SOPS_ENV_FILE: /app/.sops.env
    entrypoint: /usr/local/bin/sops-entrypoint.sh
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The entrypoint decrypts to a temp file, sources it into env, then deletes it and execs the original command. Plaintext never touches disk.

## Day-to-day operations

| Task | Command |
|---|---|
| View decrypted value | `sops --decrypt backend/.sops.env` |
| Edit encrypted file in $EDITOR | `bash scripts/sops-bootstrap.sh edit backend/.sops.env` |
| Add a new key | `sops backend/.sops.env` — add the new key, save, exit |
| Rotate an operator | Edit `.sops.yaml`, then `sops updatekeys backend/.sops.env` |
| Add a new operator | Same as rotate — append their public key, run `updatekeys` |
| Emergency: encrypted file unreadable | All private keys lost = unrecoverable. **Keep multiple backups.** |

## Production deployment

- **Never** ship plaintext `.env` with the image
- Production age private key lives in:
  - A locked physical USB / hardware token (cold storage)
  - 1Password / Bitwarden vault (operational copy)
  - The deployment host's `/etc/vizor/age/keys.txt` (chmod 0400, owned by service user)
- Rotate the production age key annually or after any suspected leak
- `sops updatekeys` after any key change so all encrypted files re-encrypt to current key set

## CI / GitHub Actions

Store the age private key as a GH Actions secret named `SOPS_AGE_KEY` (the raw file content). In the workflow:

```yaml
- name: Decrypt env for tests
  env:
    SOPS_AGE_KEY: ${{ secrets.SOPS_AGE_KEY }}
  run: sops --decrypt backend/.sops.env > backend/.env
```

The plaintext `.env` is created in the runner workspace only; ephemeral, gone with the runner.

## What is encrypted

At minimum:

- `JWT_SECRET_KEY`
- `DATABASE_URL` (contains password)
- ONVIF device credentials
- Any SMTP / Twilio / Firebase keys
- Webhook signing secrets
- License server tokens
- NGC API key (for downloading pretrained models in CI)

## Threat model

| Attack | Mitigation |
|---|---|
| Repo cloned by attacker | All secrets are SOPS-encrypted; attacker needs age private key |
| Container image leaked | Encrypted env baked in; image alone is useless without age key |
| CI logs printed | `sops-entrypoint.sh` never echoes values; verify your CI doesn't `env` dump |
| Operator laptop stolen | Encrypted disk + screen lock; rotate age key + `updatekeys` |
| Insider threat | Per-operator age keys → revoke individual without touching others |
| age private key in repo (mistake) | `.gitignore` covers `keys.txt`, `age-key.txt`, `*.age`, `age/keys*` |
