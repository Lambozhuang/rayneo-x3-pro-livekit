# Stop a test session: kill the app on the glasses and bring the backend down.
# The opposite of a launch (glasses.ps1) + `docker compose up` on the lab.
#
#   .\deploy\stop.ps1                 stop the app, then `docker compose down` on the lab PC
#   .\deploy\stop.ps1 -Host mac-mini  same, against a different ssh host
#   .\deploy\stop.ps1 -SkipGlasses    only bring the backend down (glasses not on USB)
#
# Run from the repo root. Needs adb on PATH (for the app) and ssh access to the
# host that runs the backend. Nothing here touches the host beyond the compose
# project in the repo.
param(
    [string]$RemoteHost = "ylab-pc",
    [string]$RepoPath = "services/rayneo-x3-pro-livekit",
    [switch]$SkipGlasses
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

if (-not $SkipGlasses) {
    # Reuse glasses.ps1 so the package name lives in one place. If the glasses
    # are not plugged in it throws; the backend still comes down below.
    try { & (Join-Path $PSScriptRoot "glasses.ps1") -Stop }
    catch { Write-Warning "app not stopped: $_" }
}

Write-Host "backend down on ${RemoteHost}..."
& ssh $RemoteHost "cd $RepoPath/backend && docker compose down"
