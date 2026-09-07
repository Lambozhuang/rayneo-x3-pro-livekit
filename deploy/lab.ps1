# The lab PC, by hand. Windows 10; Docker is either Docker Desktop or, to stay
# clear of Desktop's licensing, plain Docker Engine inside the WSL Ubuntu. The
# script picks whichever `docker` it finds: on the Windows PATH first, else via
# `wsl -e docker`.
#
# This machine is on its own network; nothing else can reach it, so everything
# here is meant to be typed by a person. One script, four verbs:
#
#   .\deploy\lab.ps1 setup    fetch livekit-server, generate keys, write livekit.yaml + backend\.env
#   .\deploy\lab.ps1 up       start livekit-server (own window) and docker compose up -d --build
#   .\deploy\lab.ps1 status   what is listening, does /getToken answer, the adb command to use
#   .\deploy\lab.ps1 down     stop both
#
# Run from the repo root in PowerShell. `setup` is once per machine; it never
# overwrites a file that already exists. livekit-server runs on Windows itself,
# not in Docker or WSL: WSL2 on Win10 is NAT-only and the glasses' media UDP has
# to land on this host's real address. See backend/docker-compose.yml.
#
# With the engine in WSL, `host.docker.internal` resolves to the WSL VM, not to
# Windows, so `up` rewrites LIVEKIT_URL in backend\.env to Windows' address as
# seen from WSL (its default gateway, which can change across reboots), and
# Windows Firewall must let that subnet in on 7880; `status` prints the rule.

param(
    [Parameter(Position = 0)][ValidateSet("setup", "up", "down", "status")][string]$Verb = "status",
    [string]$LanIp,                       # override if the guess below picks the wrong NIC
    [string]$LiveKitVersion = "1.13.6"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Yaml = Join-Path $Root "livekit.yaml"        # gitignored; real keys
$EnvFile = Join-Path $Root "backend\.env"     # gitignored; real keys
$BinDir = Join-Path $env:LOCALAPPDATA "livekit"
$Exe = Join-Path $BinDir "livekit-server.exe"

# How to reach docker: native, or through WSL. Everything below calls Docker
# with `Docker compose ...`, and wsl.exe inherits the Windows cwd as /mnt/...
$DockerCmd = if (Get-Command docker -ErrorAction SilentlyContinue) { @("docker") } else { @("wsl", "-e", "docker") }
$DockerInWsl = $DockerCmd[0] -eq "wsl"

function Docker { & $DockerCmd[0] @($DockerCmd[1..$DockerCmd.Length] + $args) }

function Get-WslHostIp {
    # Windows, as WSL sees it: the default gateway of the WSL VM.
    (wsl -e sh -c "ip route show default | awk '{print `$3}'").Trim()
}

function Get-LanIp {
    if ($LanIp) { return $LanIp }
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -AddressFamily IPv4 |
        Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
    if (-not $route) { throw "no default route; pass -LanIp <this PC's lab address>" }
    (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 |
        Where-Object { $_.PrefixOrigin -ne "WellKnown" } | Select-Object -First 1).IPAddress
}

function Get-EnvValue([string]$Key) {
    (Select-String -Path $EnvFile -Pattern "^$Key=(.*)$").Matches[0].Groups[1].Value
}

function Invoke-Setup {
    if (-not (Test-Path $Exe)) {
        $zip = "livekit_${LiveKitVersion}_windows_amd64.zip"
        $url = "https://github.com/livekit/livekit/releases/download/v${LiveKitVersion}/$zip"
        Write-Host "downloading $url"
        New-Item -ItemType Directory -Force $BinDir | Out-Null
        Invoke-WebRequest $url -OutFile (Join-Path $BinDir $zip)
        Expand-Archive (Join-Path $BinDir $zip) $BinDir -Force
        Remove-Item (Join-Path $BinDir $zip)
    }
    Write-Host "livekit-server: $(& $Exe --version)"

    Docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker is not reachable (Docker Desktop not running, or dockerd not started in WSL)" }
    Write-Host ("docker: " + $(if ($DockerInWsl) { "engine in WSL" } else { "native / Docker Desktop" }))

    if (Test-Path $Yaml) {
        Write-Host "keeping existing $Yaml"
        $key = (Select-String -Path $Yaml -Pattern "^\s+(API\w+):\s+(\S+)").Matches[0]
        $apiKey, $apiSecret = $key.Groups[1].Value, $key.Groups[2].Value
    } else {
        # generate-keys prints "API Key:  APIxxx" / "API Secret:  xxx"
        $lines = & $Exe generate-keys
        $apiKey = ($lines | Select-String "API Key:\s+(\S+)").Matches[0].Groups[1].Value
        $apiSecret = ($lines | Select-String "API Secret:\s+(\S+)").Matches[0].Groups[1].Value
        (Get-Content (Join-Path $Root "deploy\livekit.lab.yaml")) -replace "^\s+APIx+:.*$", "  ${apiKey}: ${apiSecret}" |
            Set-Content $Yaml -Encoding ascii
        Write-Host "wrote $Yaml with a fresh key pair"
    }

    if (Test-Path $EnvFile) {
        Write-Host "keeping existing $EnvFile"
    } else {
        $ip = Get-LanIp
        $google = Read-Host "GOOGLE_API_KEY (https://aistudio.google.com/apikey)"
        $env_ = Get-Content (Join-Path $Root "backend\.env.example")
        $env_ = $env_ -replace "^LIVEKIT_PUBLIC_URL=.*", "LIVEKIT_PUBLIC_URL=ws://${ip}:7880"
        $env_ = $env_ -replace "^LIVEKIT_API_KEY=.*", "LIVEKIT_API_KEY=$apiKey"
        $env_ = $env_ -replace "^LIVEKIT_API_SECRET=.*", "LIVEKIT_API_SECRET=$apiSecret"
        $env_ = $env_ -replace "^GOOGLE_API_KEY=.*", "GOOGLE_API_KEY=$google"
        $env_ | Set-Content $EnvFile -Encoding ascii
        Write-Host "wrote $EnvFile (AUTH_MODE=dev, LIVEKIT_PUBLIC_URL=ws://${ip}:7880)"
    }
    Write-Host "`nnext: .\deploy\lab.ps1 up"
}

function Invoke-Up {
    foreach ($f in $Yaml, $EnvFile) { if (-not (Test-Path $f)) { throw "$f missing; run setup first" } }
    if (-not (Get-NetTCPConnection -LocalPort 7880 -State Listen -ErrorAction SilentlyContinue)) {
        # Its own window so the log stays visible and closing it stops the server.
        # Windows Firewall will ask once about this exe; allow it on private networks.
        Start-Process $Exe -ArgumentList "--config", "`"$Yaml`"", "--bind", "0.0.0.0" -WorkingDirectory $Root
        $deadline = (Get-Date).AddSeconds(15)
        while ((Get-Date) -lt $deadline -and -not (Get-NetTCPConnection -LocalPort 7880 -State Listen -ErrorAction SilentlyContinue)) {
            Start-Sleep -Milliseconds 500
        }
    }
    Write-Host "livekit-server: $(try { (Invoke-WebRequest http://127.0.0.1:7880/ -UseBasicParsing).StatusCode } catch { 'not answering' })"

    if ($DockerInWsl) {
        $hostIp = Get-WslHostIp
        (Get-Content $EnvFile) -replace "^LIVEKIT_URL=.*", "LIVEKIT_URL=ws://${hostIp}:7880" | Set-Content $EnvFile -Encoding ascii
        Write-Host "engine is in WSL: LIVEKIT_URL=ws://${hostIp}:7880 (Windows as seen from WSL)"
    }
    Push-Location (Join-Path $Root "backend")
    try { Docker compose up -d --build } finally { Pop-Location }
    Start-Sleep -Seconds 10
    Invoke-Status
}

function Invoke-Down {
    Push-Location (Join-Path $Root "backend")
    try { Docker compose down } finally { Pop-Location }
    Get-Process livekit-server -ErrorAction SilentlyContinue | Stop-Process
    Write-Host "stopped"
}

function Invoke-Status {
    $ip = Get-LanIp
    $port = if (Test-Path $EnvFile) { Get-EnvValue "API_PORT" } else { "3000" }
    $lk = Get-NetTCPConnection -LocalPort 7880 -State Listen -ErrorAction SilentlyContinue
    Write-Host ("livekit-server 7880: " + $(if ($lk) { "listening" } else { "DOWN" }))
    Push-Location (Join-Path $Root "backend")
    try {
        Docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
        $reg = Docker compose logs --no-log-prefix agent 2>&1 | Select-String '"registered worker"' | Select-Object -Last 1
        Write-Host ("agent: " + $(if ($reg) { "registered with livekit-server" } else { "NOT registered yet (docker compose logs agent)" }))
    } finally { Pop-Location }
    try {
        $r = Invoke-WebRequest -Method Post -Uri "http://${ip}:${port}/getToken" -ContentType "application/json" -Body "{}" -UseBasicParsing
        Write-Host "getToken: $($r.StatusCode) $(($r.Content | ConvertFrom-Json).server_url)"
    } catch { Write-Host "getToken: $($_.Exception.Message)" }
    Write-Host @"

glasses on the same Wi-Fi, then:
  adb shell am start -n com.rayneo.x3pro.assistant/io.livekit.android.example.voiceassistant.MainActivity ``
    -e token_endpoint http://${ip}:${port}/getToken -e credential ""
watch:  cd backend; $($DockerCmd -join ' ') compose logs -f agent      (look for "session for user=" and image_tokens)

if the glasses cannot connect, Windows Firewall is the usual reason; run as admin once:
  New-NetFirewallRule -DisplayName "livekit signaling" -Direction Inbound -Protocol TCP -LocalPort 7880,7881 -Profile Private -Action Allow
  New-NetFirewallRule -DisplayName "livekit media"     -Direction Inbound -Protocol UDP -LocalPort 50000-60000 -Profile Private -Action Allow
  New-NetFirewallRule -DisplayName "rayneo api"        -Direction Inbound -Protocol TCP -LocalPort ${port} -Profile Private -Action Allow
"@
    if ($DockerInWsl) {
        Write-Host @"
with the engine in WSL the containers reach livekit-server through the WSL adapter, which Windows
treats as a separate network; if the agent never registers, also (as admin):
  New-NetFirewallRule -DisplayName "livekit from WSL" -Direction Inbound -Protocol TCP -LocalPort 7880 -InterfaceAlias "vEthernet (WSL)" -Action Allow
  (Get-NetAdapter | Where-Object Name -like "vEthernet (WSL*") shows the exact alias if that one does not match
"@
    }
}

switch ($Verb) {
    "setup"  { Invoke-Setup }
    "up"     { Invoke-Up }
    "down"   { Invoke-Down }
    "status" { Invoke-Status }
}
