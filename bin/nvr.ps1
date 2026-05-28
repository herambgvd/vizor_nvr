#Requires -Version 5.1
# =============================================================================
# nvr.ps1 — cross-platform NVR stack manager (PowerShell edition)
# =============================================================================
# Usage:
#   .\bin\nvr.ps1 up              — seed go2rtc config + docker compose up -d
#   .\bin\nvr.ps1 down            — docker compose down
#   .\bin\nvr.ps1 logs [service]  — follow logs (default: backend)
#   .\bin\nvr.ps1 rebuild         — rebuild images + bring up
#   .\bin\nvr.ps1 migrate         — run alembic upgrade head
#   .\bin\nvr.ps1 ps              — show container status
#   .\bin\nvr.ps1 restart         — restart all services
# =============================================================================

param(
    [Parameter(Position=0)]
    [string]$Command = 'help',
    [Parameter(Position=1, ValueFromRemainingArguments=$true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$Compose   = "docker compose -f `"$RepoRoot\docker-compose.yml`""

function Run-Compose {
    param([string[]]$Args)
    $expr = "$Compose $($Args -join ' ')"
    Invoke-Expression $expr
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Command) {
    'up' {
        & "$RepoRoot\scripts\seed-go2rtc-config.ps1"
        Run-Compose @('up', '-d') + $Rest
    }

    'down' {
        Run-Compose @('down') + $Rest
    }

    'logs' {
        $svc = if ($Rest.Count -gt 0) { $Rest[0] } else { 'backend' }
        Run-Compose @('logs', '-f', $svc)
    }

    'rebuild' {
        Run-Compose @('build')
        Run-Compose @('up', '-d') + $Rest
    }

    'migrate' {
        Run-Compose @('run', '--rm', 'migrate', 'alembic', 'upgrade', 'head')
    }

    'ps' {
        Run-Compose @('ps') + $Rest
    }

    'restart' {
        Run-Compose @('restart') + $Rest
    }

    { $_ -in 'help', '--help', '-h' } {
        Write-Host @"
nvr.ps1 — GVD NVR stack manager

Commands:
  up              Seed go2rtc config and start the full stack
  down            Stop all services
  logs [service]  Tail logs (default: backend)
  rebuild         Rebuild images and restart
  migrate         Apply database migrations
  ps              Show container status
  restart         Restart all services

Examples:
  .\bin\nvr.ps1 up
  .\bin\nvr.ps1 logs nginx
  .\bin\nvr.ps1 rebuild
"@
    }

    default {
        Write-Host "Unknown command: $Command" -ForegroundColor Red
        Write-Host "Run: .\bin\nvr.ps1 help"
        exit 1
    }
}
