# Record source video with the glasses' stock camera, driven over adb.
#
#   .\deploy\record.ps1 -Start                    open the camera app, record, and keep recording (see below)
#   .\deploy\record.ps1 -Stop -Name layout1       stop, pull the clips to tmp\videos\layout1_pN.mp4, join them as layout1.mp4
#
# The stock app records HEVC 2432x1824 at 30 fps, ~18 Mbps, portrait by rotation
# metadata: better than the call's 1080p15 stream, so degraded variants can be
# derived with ffmpeg later. It also stops every clip at 60 s and cannot be told
# otherwise, so -Start stays in the foreground, watches for a clip to close,
# beeps, starts the next one, and beeps again: a gap of about two seconds in
# which the wearer should hold still. -Stop from another shell ends the loop
# through a marker file. The join is a plain concat, so the gaps are jumps in
# the joined file; the per-clip durations are printed for the record.
# The app is opened in video mode by intent; should it still take a picture,
# -Stop says so. Needs adb; ffmpeg/ffprobe on PATH for the join.

param(
    [switch]$Start,
    [switch]$Stop,
    [string]$Name
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Camera = "com.leiniao.camera/com.android.camera.CameraActivity"
$Dcim = "/sdcard/DCIM/Camera"
$Videos = Join-Path $Root "tmp\videos"
$Marker = Join-Path $Videos ".recording"   # the DCIM listing when recording began
$StopFile = Join-Path $Videos ".stop"      # -Stop writes the name here; -Start's loop picks it up

$devices = (& adb devices) -match "\tdevice$"
if (-not $devices) { throw "no glasses on adb" }

function Listing { (& adb shell ls $Dcim) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
function Clips($before) { Listing | Where-Object { $_ -notin $before -and $_ -like "VID_*.mp4" } }
function Beep($n) { try { 1..$n | ForEach-Object { [console]::Beep(1200, 250); Start-Sleep -Milliseconds 100 } } catch { } }

if ($Start) {
    New-Item -ItemType Directory -Force $Videos | Out-Null
    Remove-Item $StopFile -ErrorAction SilentlyContinue
    $before = Listing
    $before | Set-Content $Marker
    & adb shell input keyevent KEYCODE_WAKEUP
    & adb shell am start -a android.media.action.VIDEO_CAMERA -n $Camera | Out-Null  # video mode, whatever mode it was left in
    Start-Sleep -Seconds 3
    & adb shell input keyevent KEYCODE_CAMERA
    Write-Host "recording; stop from another shell with: .\deploy\record.ps1 -Stop -Name <name>"
    $seen = @(Clips $before)
    while (-not (Test-Path $StopFile)) {
        Start-Sleep -Milliseconds 500
        $now = @(Clips $before)
        if ($now.Count -gt $seen.Count) {
            # a clip closed on its own (the 60 s limit): start the next one
            Beep 1
            & adb shell input keyevent KEYCODE_CAMERA
            Beep 2
            Write-Host "clip $($now.Count) closed at $(Get-Date -Format HH:mm:ss); next one started"
            $seen = $now
        }
    }
    $Name = (Get-Content $StopFile).Trim()
    & adb shell input keyevent KEYCODE_CAMERA
    Start-Sleep -Seconds 3
    & adb shell am force-stop ($Camera -split "/")[0]
    $clips = @(Clips $before)
    if (-not $clips) {
        Remove-Item $StopFile, $Marker -ErrorAction SilentlyContinue
        if (Listing | Where-Object { $_ -notin $before -and $_ -like "IMG_*" }) { throw "the camera app was in photo mode (it took a picture); record again" }
        throw "no new clip in $Dcim"
    }
    $list = Join-Path $Videos "$Name.txt"
    "" | Set-Content $list
    $i = 0
    foreach ($clip in $clips) {
        $i++
        $out = Join-Path $Videos "${Name}_p$i.mp4"
        & adb pull "$Dcim/$clip" $out | Out-Null
        $dur = if (Get-Command ffprobe -ErrorAction SilentlyContinue) {
            (& ffprobe -v error -show_entries format=duration -of csv=p=0 $out).Trim()
        } else { "?" }
        Add-Content $list "file '${Name}_p$i.mp4'"
        Write-Host "pulled $clip -> ${Name}_p$i.mp4  ${dur}s"
    }
    if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and $i -gt 1) {
        Push-Location $Videos
        & ffmpeg -v error -y -f concat -safe 0 -i "$Name.txt" -c copy "$Name.mp4"
        Pop-Location
        Write-Host "joined -> $Name.mp4 ($i clips; each join is a ~2 s jump)"
    } elseif ($i -eq 1) {
        Move-Item -Force (Join-Path $Videos "${Name}_p1.mp4") (Join-Path $Videos "$Name.mp4")
        Write-Host "-> $Name.mp4"
    }
    Remove-Item $StopFile, $Marker, $list -ErrorAction SilentlyContinue
    return
}

if ($Stop) {
    if (-not $Name) { $Name = "rec_" + (Get-Date -Format yyyyMMdd_HHmmss) }
    if (-not (Test-Path $Marker)) { throw "nothing is recording (no $Marker)" }
    $Name | Set-Content $StopFile
    Write-Host "stopping as '$Name'; the -Start shell pulls and joins the clips"
    $t0 = Get-Date
    while ((Test-Path $StopFile) -and ((Get-Date) - $t0).TotalSeconds -lt 120) { Start-Sleep -Milliseconds 500 }
    if (Test-Path $StopFile) { throw "the -Start loop did not pick up the stop; is it still running?" }
    Get-ChildItem (Join-Path $Videos "$Name*.mp4") | ForEach-Object { Write-Host $_.Name }
    return
}

Write-Host "use -Start or -Stop"
