# Vizor NVR License Generator

Support-team web application for creating signed Vizor NVR `.lic` files.

## Run locally

```bash
cd /home/gvd-ai/office/clarify/vizor_nvr
python3 -m venv .venv-license
. .venv-license/bin/activate
pip install -r scripts/license_web/requirements.txt
python3 scripts/license_web/app.py
```

Open:

```text
http://127.0.0.1:5055
```

## What it stores

By default:

```text
scripts/license_web.sqlite3         # local license/client history
vendor-keys/<client>/private.pem    # client private signing key
vendor-keys/<client>/public.b64     # matching public key for that client's NVR
vendor-keys/<client>/licenses/*.lic # generated license files
```

Important: if each client has a separate keypair, that client's deployed NVR
must use the matching `public.b64`.

## Feature model

Top-level modules:

- `recording`
- `playback`
- `frs`
- `ppe`
- `anpr`
- `people_counting`
- `suspect_search`

FRS sub-features:

- `attendance`
- `investigation`

The generated payload uses:

```json
{
  "features": ["recording", "playback", "frs"],
  "scenarios": ["frs"],
  "feature_options": {
    "frs": ["attendance", "investigation"]
  }
}
```
