# Launch the app on the glasses over adb, in one step.
#
#   .\deploy\glasses.ps1                          launch, pointed at this PC's LAN IP, api port from backend\.env
#   .\deploy\glasses.ps1 -Ip 192.168.50.147       point at another backend
#   .\deploy\glasses.ps1 -Install                 build the debug APK and install it first
#   .\deploy\glasses.ps1 -Log                     after launching, tail the touchpad/gesture log (Ctrl+C to stop)
#   .\deploy\glasses.ps1 -Stop                    kill the app on the glasses (same as double-tapping out of it)
#
# The app remembers the last endpoint it was given, and goes straight into the
# call on launch, so once this has run once the launcher icon does the same.
# Run from the repo root. Needs adb on PATH and the glasses plugged in (USB is
# for launching and logs only; the call itself is Wi-Fi).

param(
    [string]$Ip,                  # backend LAN address; default: this PC's
    [string]$Port,                # api port; default: API_PORT from backend\.env, else 3000
    [string]$Credential = "",     # AUTH_STATIC_TOKEN when the api runs with AUTH_MODE=static
    [switch]$Install,
    [switch]$Log,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Pkg = "com.rayneo.x3pro.assistant"
$Activity = "$Pkg/io.livekit.android.example.voiceassistant.MainActivity"

if (-not $Ip) {
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -AddressFamily IPv4 |
        Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
    $Ip = (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 |
        Where-Object { $_.PrefixOrigin -ne "WellKnown" } | Select-Object -First 1).IPAddress
}
if (-not $Port) {
    $envFile = Join-Path $Root "backend\.env"
    $m = if (Test-Path $envFile) { Select-String -Path $envFile -Pattern "^API_PORT=(\d+)" } else { $null }
    $Port = if ($m) { $m.Matches[0].Groups[1].Value } else { "3000" }
}
$Endpoint = "http://${Ip}:${Port}/getToken"

$devices = (& adb devices) -match "\tdevice$"
if (-not $devices) { throw "no glasses on adb (adb devices shows nothing in state 'device')" }

if ($Stop) {
    & adb shell am force-stop $Pkg
    Write-Host "stopped $Pkg"
    return
}

if ($Install) {
    # Gradle needs a JDK; Android Studio ships one, and a PowerShell session
    # usually has no JAVA_HOME. Fall back to Studio's if it is there.
    if (-not $env:JAVA_HOME) {
        $jbr = Join-Path ${env:ProgramFiles} "Android\Android Studio\jbr"
        if (Test-Path $jbr) { $env:JAVA_HOME = $jbr } else { throw "JAVA_HOME is not set and Android Studio's JDK was not found at $jbr" }
    }
    Push-Location (Join-Path $Root "android")
    try { & .\gradlew -q :app:assembleDebug; if ($LASTEXITCODE -ne 0) { throw "build failed" } } finally { Pop-Location }
    & adb install -r (Join-Path $Root "android\app\build\outputs\apk\debug\app-debug.apk") | Select-Object -Last 1
}

# The glasses have been found with Wi-Fi off; the call cannot happen without it.
if ((& adb shell settings get global wifi_on).Trim() -ne "1") {
    Write-Host "wifi was off; enabling"
    & adb shell svc wifi enable | Out-Null
    Start-Sleep -Seconds 3
}

# Asleep glasses (taken off for a minute) keep the app out of the foreground.
& adb shell input keyevent KEYCODE_WAKEUP

# An empty -e credential "" is eaten by the shell and `am start` then fails
# with "Argument expected"; only pass it when there is one.
$extras = @("-e", "token_endpoint", $Endpoint)
if ($Credential) { $extras += @("-e", "credential", $Credential) }
& adb shell am start -n $Activity @extras | Select-Object -Last 1
Write-Host "launched -> $Endpoint"

if ($Log) {
    # The LiveKit SDK logs at DEBUG and rolls the default 256 KB buffer in
    # seconds; filter by tag so the gestures are the only thing on screen.
    & adb logcat -v time -s rayneo-input
}
