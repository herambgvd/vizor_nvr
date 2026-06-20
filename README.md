# GVD NVR

Enterprise-grade Network Video Recorder built on FastAPI + React, with ONVIF support, go2rtc restreaming, and a Docker-first deployment model.

> **New developer?** Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first — it maps the repo, the module pattern, API conventions, and the dev loop. The full docs index is in §8 there.

## Quick Start

**Linux / macOS**

```bash
sudo bash install.sh
```

After install, open **https://localhost** in your browser (accept the self-signed certificate warning) and log in with the admin credentials you entered during setup.

## Full Installation Guides

- [Linux Installation Guide](docs/INSTALL_LINUX.md)

## Managing the Stack

| Platform | Command |
|---|---|
| Linux / macOS | `bin/nvr.sh <command>` or `make <target>` |

Common commands: `up` · `down` · `logs [service]` · `rebuild` · `migrate` · `ps`

## Architecture

```mermaid
flowchart TD
    subgraph Devices["IP Cameras / ONVIF Devices"]
        CAM[Camera — RTSP / ONVIF]
        ONVIF_DEV[NVR-as-Camera\nONVIF Device Server]
    end

    subgraph NVR["NVR Host (Docker Compose)"]
        NGINX[nginx\nTLS termination\nreverse proxy]
        BE[backend\nFastAPI + SQLAlchemy]
        GO2RTC[go2rtc\nRTSP restreamer\nport 1984]
        PG[(PostgreSQL\nmetadata + audit)]
        REC[(recordings volume\nmp4 segments)]
        CERTS[(certs volume\nTLS PEM files)]
    end

    subgraph Clients["Clients"]
        BROWSER[PWA / Browser]
        MOBILE[Mobile app]
        VMS[External VMS\nvia ONVIF]
        API[API client\ncurl / SDK]
    end

    CAM -->|RTSP stream| GO2RTC
    CAM -->|ONVIF SOAP / WS-Discovery| BE
    GO2RTC -->|WebRTC / HLS| NGINX
    GO2RTC -->|mux recordings| REC
    BE <-->|async SQL| PG
    BE -->|write segments| REC
    BE <-->|stream config / health| GO2RTC
    NGINX -->|/api| BE
    NGINX -->|/| BE
    NGINX --- CERTS
    ONVIF_DEV <-->|ONVIF Profile S/T| VMS
    BE <-->|ONVIF Device API| ONVIF_DEV
    BROWSER --> NGINX
    MOBILE --> NGINX
    VMS --> ONVIF_DEV
    API --> NGINX
```

**Data flow summary**: Cameras push RTSP streams to go2rtc, which forwards them to browsers via WebRTC and muxes recordings to disk. The FastAPI backend orchestrates ONVIF device management, writes metadata to PostgreSQL, and serves the React frontend through nginx. External VMS systems connect to the built-in ONVIF Device Server. All external traffic terminates at nginx with TLS.

## Component Table

| Component | Description |
|---|---|
| `backend/` | FastAPI + SQLAlchemy async + Alembic migrations |
| `frontend/` | React + shadcn/ui |
| `scenarios/` | AI plug-ins (FRS, Suspect Search, PPE) — standalone FastAPI services |
| `triton/` | Shared GPU inference server for the AI scenarios |
| go2rtc | RTSP restreamer (port 1984) |
| nginx | TLS termination + reverse proxy |
