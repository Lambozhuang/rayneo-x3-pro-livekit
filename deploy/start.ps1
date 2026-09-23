# Start a test session in one step: backend on the lab PC, app on the glasses.
#
#   .\deploy\start.ps1 -Backend gemini              Gemini Live path on ylab-pc, then launch the glasses
#   .\deploy\start.ps1 -Backend openai              GPT-Live path
#   .\deploy\start.ps1 -Backend openai -RemoteHost lambos-ubuntu -RepoPath Workspace/rayneo-x3-pro-livekit
#   .\deploy\start.ps1 -Backend gemini -SkipGlasses  backend only (glasses not on USB)
#   .\deploy\start.ps1 -Backend openai -Log          then tail the agent log through watch.py (Ctrl+C to stop)
#
# What it does on the host, inside the repo's compose project and nothing else:
# git pull, set AGENT_BACKEND in backend/.env, `docker compose up -d --build`,
# wait for the agent to register. Then glasses.ps1 -Ip <the host's
# LIVEKIT_PUBLIC_URL address>. The opposite is stop.ps1. Run from the repo
# root; needs ssh to the host and adb for the glasses.
param(
    [Parameter(Mandatory = $true)][ValidateSet("gemini", "openai")][string]$Backend,
    [string]$RemoteHost = "ylab-pc",
    [string]$RepoPath = "services/rayneo-x3-pro-livekit",
    [switch]$SkipGlasses,
    [switch]$Log,
    [switch]$NoPull
)
$ErrorActionPreference = "Stop"

$pull = if ($NoPull) { "true" } else { "git pull -q" }
# One ssh call: pull, switch the backend in .env (add the line if missing), rebuild, wait for registration.
$remote = @"
set -e
cd $RepoPath && $pull
cd backend
grep -q '^AGENT_BACKEND=' .env && sed -i 's/^AGENT_BACKEND=.*/AGENT_BACKEND=$Backend/' .env || printf '\nAGENT_BACKEND=$Backend\n' >> .env
docker compose up -d --build 2>&1 | tail -3
for i in `$(seq 1 30); do
  docker compose logs --no-log-prefix --since 40s agent 2>/dev/null | grep -q 'registered worker' && break
  sleep 1
done
docker compose logs --no-log-prefix --since 40s agent 2>/dev/null | grep -q 'registered worker' && echo 'agent registered' || { echo 'agent did not register in 30 s'; docker compose logs --no-log-prefix --since 40s agent | tail -20; exit 1; }
grep '^LIVEKIT_PUBLIC_URL=' .env | sed -E 's#.*//([^:/]+).*#IP=\1#'
"@

Write-Host "backend=$Backend on ${RemoteHost}..."
$out = & ssh $RemoteHost $remote
$out | Where-Object { $_ -notmatch '^IP=' } | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { throw "backend start failed on $RemoteHost" }
$ip = ($out | Where-Object { $_ -match '^IP=' } | Select-Object -Last 1) -replace '^IP=', ''
if (-not $ip) { throw "could not read LIVEKIT_PUBLIC_URL from the host's backend/.env" }

if (-not $SkipGlasses) {
    & (Join-Path $PSScriptRoot "glasses.ps1") -Ip $ip
}

if ($Log) {
    & ssh $RemoteHost "cd $RepoPath/backend && docker compose logs -f --no-log-prefix agent" | python (Join-Path $PSScriptRoot "watch.py") -v
}
