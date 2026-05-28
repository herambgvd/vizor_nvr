@echo off
:: =============================================================================
:: nvr.cmd — thin shim that delegates to nvr.ps1
:: =============================================================================
:: Allows running `nvr up` from a plain cmd.exe or Windows Explorer without
:: needing to type the .ps1 extension or set execution policy manually.
::
:: Usage (from repo root):
::   bin\nvr up
::   bin\nvr logs backend
::   bin\nvr rebuild
:: =============================================================================

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
    -File "%~dp0nvr.ps1" %*
