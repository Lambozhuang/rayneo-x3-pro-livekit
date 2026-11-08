# Launch the app on the glasses over adb, in one step.
#
#   .\deploy\glasses.ps1                          launch, pointed at this PC's LAN IP, api port from backend\.env
#   .\deploy\glasses.ps1 -Ip 192.168.50.147       point at another backend
#   .\deploy\glasses.ps1 -Install                 build the debug APK and install it first
#   .\deploy\glasses.ps1 -Lab 192.168.50.177      name the QoE Lab console (port 8080 unless given) for the menu's Lab
#                                                 entry, where the console starts and ends the tasks (Lab.kt)
#   .\deploy\glasses.ps1 -Task flag               preselect a build in the Debug picker (swipe changes it); a game's
#                                                 trial is a build here too (-Task b-1, backend/agent/guides)
#   .\deploy\glasses.ps1 -Lab <ip> -Game B         make the lab session a block of the user study's game B: the
#                                                 console's run numbers name the trial files b-1 to b-6 (Lab.kt)
#   .\deploy\glasses.ps1 -MaxKbps 250             cap the camera track's bitrate for this launch's calls, in kbit/s
#                                                 (Uplink.kt); 4000 without it; stands in for a link cap at home
#   .\deploy\glasses.ps1 -Record                  record the calls of this launch on the glasses (Recording.kt);
#                                                 any launch without it turns recording off
#   .\deploy\glasses.ps1 -MockLab after            open the app on the lab screen as it looks between tasks, without a
#                                                 console (Lab.mock); also waiting and problem
#   .\deploy\glasses.ps1 -Mock                    open the app on the mock call screen (MockScreen.kt): the gate at
#                                                 step 2 playing a scene of the call's states on a loop, no server
#                                                 needed; double tap leaves
#   .\deploy\glasses.ps1 -Exposure -4             set the camera's exposure compensation for this launch's calls, in
#                                                 sixths of an EV, -12..12 (Exposure.kt); a launch without it uses -2,
#                                                 the lab's value since 2026-11-04 (-6 read a yellow brick as orange);
#                                                 -Exposure 0 is the camera's own
#   .\deploy\glasses.ps1 -ExposureSweep           record the desk as -Record would, 5 s at each of the compensations
#                                                 0, -2, -4 and -6, and pull it into logs\exposure-<time>\; no server
#   .\deploy\glasses.ps1 -Log                     after launching, tail the touchpad/gesture log (Ctrl+C to stop)
#   .\deploy\glasses.ps1 -Stop                    kill the app on the glasses (same as double-tapping out of it)
#   .\deploy\glasses.ps1 -RestoreSleep            put RayNeo's deep suspend back (launch turns it off, see below)
#
# The app remembers the last endpoint, console and build it was given, and opens
# on the menu: Lab or Debug; swipe on the temple to choose, tap to enter.
# Run from the repo root. Needs adb on PATH and the glasses plugged in (USB is
# for launching and logs only; the call itself is Wi-Fi). -Install builds the
# debug variant on purpose: it is the one that allows cleartext http:// and
# ws:// to a LAN IP. It needs a JDK: JAVA_HOME, or Android Studio's.

param(
    [string]$Ip,                  # backend LAN address; default: this PC's
    [string]$Port,                # api port; default: API_PORT from backend\.env, else 3000
    [string]$Credential = "",     # AUTH_STATIC_TOKEN when the api runs with AUTH_MODE=static
    [string]$Lab = "",            # the QoE Lab console, <ip> or <ip>:<port>; the Lab entry connects there
    [string]$Task = "",           # a build's name (backend/agent/guides/<name>) to preselect
    [string]$Game = "",           # A or B: the lab session is a block of that game of the user study (Lab.kt)
    [int]$MaxKbps = 0,            # cap the camera track's bitrate in kbit/s; 0 = the app's 4000 (Uplink.kt)
    [switch]$Record,              # record every call of this launch: camera as the call sees it, mic, agent voice
    [switch]$Mock,                # open on the mock call screen, a scripted scene, instead of the build picker
    [string]$MockLab,             # open on the lab screen in this stage with no console: waiting, after, problem (Lab.mock)
    [int]$Exposure = -2,          # exposure compensation index for the calls, -12..12; the lab's -2 unless given
    [switch]$ExposureSweep,       # record the desk at several compensations, pull the recording, then leave
    [switch]$Install,
    [switch]$Log,
    [switch]$Stop,
    [switch]$RestoreSleep
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Pkg = "com.rayneo.x3pro.assistant"
$Activity = "$Pkg/io.livekit.android.example.voiceassistant.MainActivity"

# adb refuses every command when more than one device is attached, as when an emulator runs for mock screenshots
# beside the glasses (2026-11-08): take the first attached device that is not an emulator.
$attached = @(& adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "`tdevice$" } | ForEach-Object { ($_ -split "`t")[0] })
if ($attached.Count -gt 1) {
    $env:ANDROID_SERIAL = $attached | Where-Object { $_ -notmatch '^emulator-' } | Select-Object -First 1
    Write-Host "several devices attached ($($attached -join ', ')); using $env:ANDROID_SERIAL"
}

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

if ($RestoreSleep) {
    & adb shell settings put global deep_suspend_disabled_persist 0
    Write-Host "deep suspend restored: the glasses sleep and drop Wi-Fi a minute after being taken off"
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

# RayNeo's deep-suspend policy: a minute after the wear sensor says "taken off"
# (it also misfires while worn) the system switches Wi-Fi off. This global
# setting disables that whole path and survives reboots; while it is 1 the
# glasses neither sleep nor drop Wi-Fi when taken off, so they drain faster
# off the head. `-RestoreSleep` sets it back to 0 when the experiment is over.
if ((& adb shell settings get global deep_suspend_disabled_persist).Trim() -ne "1") {
    Write-Host "deep suspend was on; disabling (settings put global deep_suspend_disabled_persist 1)"
    & adb shell settings put global deep_suspend_disabled_persist 1
}

# The glasses have been found with Wi-Fi off; the call cannot happen without it.
if ((& adb shell settings get global wifi_on).Trim() -ne "1") {
    Write-Host "wifi was off; enabling"
    & adb shell svc wifi enable | Out-Null
    Start-Sleep -Seconds 3
}

# Asleep glasses (taken off for a minute) keep the app out of the foreground.
& adb shell input keyevent KEYCODE_WAKEUP

# The app's call, link and speech lines (rayneo-call, rayneo-link, rayneo-speech) are read back
# after the call by deploy/pull_run.py. The SDK logs at DEBUG and rolls the
# default 256 KB buffer in seconds, so a whole call has to fit: 64 MB does.
& adb logcat -G 64M

# An empty -e credential "" is eaten by the shell and `am start` then fails
# with "Argument expected"; only pass it when there is one.
$extras = @("-e", "token_endpoint", $Endpoint)
if ($Credential) { $extras += @("-e", "credential", $Credential) }
if ($Lab) { $extras += @("-e", "lab_console", "http://$(if ($Lab -match ':') { $Lab } else { "${Lab}:8080" })") }
if ($Task) { $extras += @("-e", "task", $Task) }
if ($Game) {
    if ($Game -notmatch '^[abAB]$') { throw "-Game takes A or B" }
    if (-not $Lab) { throw "-Game goes with -Lab: the game is a lab session's" }
    $extras += @("-e", "game", $Game.ToUpper())
}
if ($MaxKbps) { $extras += @("--ei", "max_kbps", $MaxKbps) }
if ($MockLab) { $extras += @("--es", "lab_mock", $MockLab) }
if ($Record) { $extras += @("--ez", "record", "true") }
if ($Exposure -lt -12 -or $Exposure -gt 12) { throw "-Exposure takes -12..12 (sixths of an EV)" }
$extras += @("--ei", "exposure", $Exposure)
if ($Mock -or $ExposureSweep -or $MockLab -or $Lab -or $MaxKbps) {
    # The start screen is chosen in onCreate, so a running instance has to go first; the bitrate cap is read there too.
    & adb shell am force-stop $Pkg
}
if ($Mock) { $extras += @("--ez", "mock", "true") }
if ($ExposureSweep) {
    # The last sweep's done marker would end the wait below before this sweep has begun.
    & adb shell rm -rf "/sdcard/Android/data/$Pkg/files/exposure"
    $extras += @("--ez", "exposure_sweep", "true")
}
& adb shell am start -n $Activity @extras | Select-Object -Last 1
Write-Host "launched -> $(if ($Mock) { 'mock call screen' } elseif ($ExposureSweep) { 'exposure sweep' } else { $Endpoint })$(if ($Lab) { ", console $Lab" })$(if ($Game) { ", game $($Game.ToUpper())" })$(if ($Record) { ', recording' })$(if ($MaxKbps) { ", $MaxKbps kbit/s" }), exposure $Exposure"

if ($ExposureSweep) {
    # The app writes exposure/done when the recording is closed; the sweep holds each of four compensations 5 s.
    $remote = "/sdcard/Android/data/$Pkg/files/exposure"
    $deadline = (Get-Date).AddSeconds(150)
    while ((& adb shell "ls $remote/done 2>/dev/null") -notmatch "done") {
        if ((Get-Date) -gt $deadline) { throw "the sweep did not finish in 150 s; see adb logcat -s rayneo-camera" }
        Start-Sleep -Seconds 2
    }
    # The storage is behind FUSE: a listing right after the marker appears has been seen without the newest files.
    Start-Sleep -Seconds 2
    $local = Join-Path $Root ("logs\exposure-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    & adb pull $remote $local | Select-Object -Last 1
    Write-Host "recording in $local (video.mp4; camera.txt says which second each compensation starts at)"
}

if ($Log) {
    # The LiveKit SDK logs at DEBUG and rolls the default 256 KB buffer in
    # seconds; filter by tag so the gestures are the only thing on screen.
    & adb logcat -v time -s rayneo-input
}
