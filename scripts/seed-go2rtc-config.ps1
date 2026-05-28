# =============================================================================
# seed-go2rtc-config.ps1 — Bootstrap go2rtc.yaml from the template (Windows)
# =============================================================================
# PowerShell equivalent of scripts/seed-go2rtc-config.sh
#
# go2rtc rewrites its config file at runtime (persisting discovered streams).
# The file must exist before `docker compose up` because the service bind-
# mounts ./go2rtc.yaml:/config/go2rtc.yaml.
#
# This script copies go2rtc.yaml.template → go2rtc.yaml ONLY if the file
# does not already exist, so a running deployment's learned streams are never
# wiped on `nvr up`.
#
# Usage (standalone):  .\scripts\seed-go2rtc-config.ps1
# Usage (install.ps1): called automatically during first-install
# Usage (nvr.ps1):     called by `nvr up`
# =============================================================================

$ErrorActionPreference = 'Stop'

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptDir
$Template   = Join-Path $RepoRoot 'go2rtc.yaml.template'
$Target     = Join-Path $RepoRoot 'go2rtc.yaml'

if (-not (Test-Path $Template)) {
    Write-Error "[seed-go2rtc] ERROR: template not found at $Template"
    exit 1
}

if (Test-Path $Target) {
    Write-Host "[seed-go2rtc] go2rtc.yaml already exists — skipping seed"
    exit 0
}

Copy-Item $Template $Target
Write-Host "[seed-go2rtc] go2rtc.yaml seeded from template"
