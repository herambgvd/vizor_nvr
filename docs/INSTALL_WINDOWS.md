# GVD NVR — Windows Installation Guide

This guide walks you through installing GVD NVR on a Windows 10/11 host using Docker Desktop.

---

## Prerequisites

| Requirement | Minimum version | Install link |
|---|---|---|
| Windows | 10 21H2 / 11 | — |
| Docker Desktop | 4.x (WSL 2 backend recommended) | https://docs.docker.com/desktop/install/windows-install/ |
| WSL 2 | Enabled | Installed automatically by Docker Desktop |
| PowerShell | 5.1 (built-in) or 7.x | https://aka.ms/powershell |

### Enable file sharing for your project drive

After installing Docker Desktop, make sure the drive that contains this repo is shared:

1. Open Docker Desktop → **Settings** → **Resources** → **File Sharing**
2. Add the drive letter (e.g., `C:\`) if it is not already listed.
3. Click **Apply & Restart**.

---

## Quick Install (interactive)

Open **PowerShell** (not cmd.exe) in the repo directory and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

The installer will prompt you for:

- Admin e-mail and password (≥ 12 characters)
- Postgres password (auto-generated random default)
- Storage path on the host (default: `C:\gvd-nvr\data`)
- HTTP / HTTPS ports (default: 80 / 443)
- Public IP or hostname for WebRTC

It then:

1. Generates `.env` with random secrets
2. Seeds `go2rtc.yaml` from the template
3. Generates a self-signed TLS certificate (requires `openssl` in PATH — see note below)
4. Runs `docker compose up -d --build`
5. Waits for the backend health endpoint to return 200
6. Creates the first admin user

### Self-signed certificate note

`New-SelfSignedCertificate` is used to generate the cert. Converting it to PEM requires `openssl` in `PATH`. The easiest way to get it is:

- **Git for Windows** (recommended) — includes `openssl.exe` in `C:\Program Files\Git\usr\bin`
- [Win32 OpenSSL](https://slproweb.com/products/Win32OpenSSL.html) (light version is enough)

If `openssl` is not found the stack will still start, but HTTPS will not work until you manually place `server.crt` and `server.key` (PEM format) into `nginx\certs\`.

---

## Non-interactive Install (CI / scripted)

```powershell
$env:NVR_ADMIN_EMAIL    = "admin@example.com"
$env:NVR_ADMIN_PASSWORD = "SuperSecret123!"
$env:NVR_PUBLIC_HOST    = "192.168.1.50"
.\install.ps1 -Quiet
```

---

## Managing the Stack

Use `bin\nvr.ps1` (PowerShell) or `bin\nvr.cmd` (cmd.exe):

```powershell
.\bin\nvr.ps1 up           # start stack
.\bin\nvr.ps1 down         # stop stack
.\bin\nvr.ps1 logs         # tail backend logs
.\bin\nvr.ps1 logs nginx   # tail a specific service
.\bin\nvr.ps1 rebuild      # rebuild images and restart
.\bin\nvr.ps1 migrate      # apply database migrations
.\bin\nvr.ps1 ps           # show container status
```

From cmd.exe:

```cmd
bin\nvr up
bin\nvr logs backend
```

---

## Post-Install Steps

1. Open your browser and go to **https://localhost** (or the HTTPS port you chose).
2. Your browser will show a certificate warning — click **Advanced** → **Proceed to localhost (unsafe)** (this is expected for self-signed certs).
3. Log in with the admin credentials you entered during install.

---

## Auto-start on Boot (optional)

Docker Desktop can be configured to start automatically with Windows, which will also start the NVR containers (Docker Desktop uses restart policies):

1. Docker Desktop → Settings → General → **Start Docker Desktop when you sign in** ✓

Alternatively, create a Windows Task Scheduler task that runs `bin\nvr.cmd up` at logon.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `docker` not found | Restart PowerShell after installing Docker Desktop |
| Port 80/443 already in use | Change `HTTP_PORT`/`HTTPS_PORT` in `.env` and run `.\bin\nvr.ps1 rebuild` |
| Containers exit immediately | Run `.\bin\nvr.ps1 logs` to see error details |
| File sharing error in Docker | Ensure the drive is listed in Docker Desktop > Resources > File Sharing |
| HTTPS cert warning | Expected for self-signed certs; click Advanced → Proceed |

---

## Uninstall

```powershell
.\bin\nvr.ps1 down
docker volume rm gvd_nvr_recordings gvd_nvr_go2rtc_data
Remove-Item .env
```

---

## Telemetry

GVD NVR ships with anonymous usage analytics (PostHog) **disabled by default**. No data leaves your server unless you explicitly opt in.

To enable telemetry, edit `frontend\public\runtime-config.js` and uncomment the opt-in line:

```js
window.__GVD_TELEMETRY__ = true;
```

Then rebuild the frontend container:

```powershell
docker compose build frontend
docker compose up -d frontend
```

To confirm the setting, open your browser's developer console on the GVD Pro UI and run `window.__GVD_TELEMETRY__`. It should return `true`.
