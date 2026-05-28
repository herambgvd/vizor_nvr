# GVD NVR — Linux Installation Guide

This guide covers installing GVD NVR on a Linux server (Ubuntu 22.04 / Debian 12 recommended, but any distro with Docker Engine works).

---

## Prerequisites

| Requirement | Minimum version |
|---|---|
| Docker Engine | 24.x |
| Docker Compose plugin | v2.x (bundled with recent Docker Engine) |
| `openssl` | Any version in PATH |
| `bash` | 4.x |

### Install Docker Engine (Ubuntu / Debian)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # allow running docker without sudo
newgrp docker                   # apply group change in current shell
```

For other distributions see: https://docs.docker.com/engine/install/

---

## Quick Install (interactive)

```bash
git clone https://github.com/yourorg/gvd-nvr.git
cd gvd-nvr
sudo bash install.sh
```

The installer will prompt you for:

- Admin e-mail and password (≥ 12 characters)
- Postgres password (auto-generated random default)
- Storage path on the host (default: `/var/lib/gvd-nvr/data`)
- HTTP / HTTPS ports (default: 80 / 443)
- Public IP or hostname for WebRTC

It then:

1. Generates `.env` with random secrets
2. Seeds `go2rtc.yaml` from the template
3. Generates a self-signed TLS certificate via `openssl`
4. Runs `docker compose pull && up -d`
5. Installs a **systemd unit** so the stack starts automatically at boot
6. Waits for the backend health endpoint to return 200
7. Creates the first admin user

---

## Non-interactive Install (CI / Ansible)

```bash
export NVR_ADMIN_EMAIL="admin@example.com"
export NVR_ADMIN_PASSWORD="SuperSecret123!"
export NVR_PUBLIC_HOST="192.168.1.50"
export NVR_STORAGE_PATH="/srv/nvr"
sudo --preserve-env bash install.sh --quiet
```

---

## Managing the Stack

Use `bin/nvr.sh` or GNU `make`:

```bash
bin/nvr.sh up           # seed go2rtc config and start stack
bin/nvr.sh down         # stop stack
bin/nvr.sh logs         # tail backend logs
bin/nvr.sh logs nginx   # tail a specific service
bin/nvr.sh rebuild      # rebuild images and restart
bin/nvr.sh migrate      # apply database migrations
bin/nvr.sh ps           # show container status
```

Or via Make:

```bash
make up
make logs
make rebuild
make migrate
```

---

## systemd Auto-start

`install.sh` installs `/etc/systemd/system/gvd-nvr.service` automatically. To manage it:

```bash
sudo systemctl status  gvd-nvr   # check status
sudo systemctl stop    gvd-nvr   # stop
sudo systemctl start   gvd-nvr   # start
sudo systemctl disable gvd-nvr   # disable auto-start
```

---

## Post-Install Steps

1. Open your browser and go to **https://\<server-ip\>** (or the hostname you set).
2. Your browser will show a certificate warning for the self-signed cert — click **Advanced** → **Proceed**.
3. Log in with the admin credentials you entered during install.

To avoid the browser warning in production, replace the self-signed cert with a valid one (Let's Encrypt via certbot, or your CA) and place the PEM files at `nginx/certs/server.crt` and `nginx/certs/server.key`, then run `bin/nvr.sh restart`.

---

## Upgrading

```bash
git pull
bin/nvr.sh rebuild
bin/nvr.sh migrate
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `docker compose` not found | Install Docker Engine via `get.docker.com` (includes compose plugin) |
| Port 80/443 already in use | Edit `HTTP_PORT`/`HTTPS_PORT` in `.env` and run `bin/nvr.sh rebuild` |
| Containers exit immediately | Run `bin/nvr.sh logs` to see error details |
| `Permission denied` on storage path | `sudo chown -R $USER:$USER /var/lib/gvd-nvr` |

---

## Uninstall

```bash
bin/nvr.sh down
docker volume rm gvd_nvr_recordings gvd_nvr_go2rtc_data
sudo systemctl disable gvd-nvr
sudo rm /etc/systemd/system/gvd-nvr.service
rm .env
```
