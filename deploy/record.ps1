# Record source video with the glasses' stock camera, driven over adb.
#
#   .\deploy\record.ps1 -Start                    open the camera app and start recording
#   .\deploy\record.ps1 -Stop -Name layout1       stop, pull the clip to tmp\videos\<Name>.mp4, print its specs
#   .\deploy\record.ps1 -Stop                     same, named by the clip's timestamp
#
# The stock app records HEVC 2432x1824 at 30 fps, ~18 Mbps, portrait by rotation
# metadata: better than the call's 1080p15 stream, so degraded variants can be
# derived with ffmpeg later. The app is opened in video mode by intent and the
# camera key starts and stops recording; should it still be in photo mode, -Stop
# says so. Needs adb; ffprobe if on PATH.

param(
    [switch]$Start,
    [switch]$Stop,
    [string]$Name
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Camera = "com.leiniao.camera/com.android.camera.CameraActivity"
$Dcim = "/sdcard/DCIM/Camera"
$Marker = Join-Path $Root "tmp\videos\.recording"

$devices = (& adb devices) -match "\tdevice$"
if (-not $devices) { throw "no glasses on adb" }

function Listing { (& adb shell ls $Dcim) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ } }

if ($Start) {
    New-Item -ItemType Directory -Force (Split-Path $Marker) | Out-Null
    Listing | Set-Content $Marker
    & adb shell input keyevent KEYCODE_WAKEUP
    & adb shell am start -a android.media.action.VIDEO_CAMERA -n $Camera | Out-Null  # open in video mode, whatever mode it was left in
    Start-Sleep -Seconds 3
    & adb shell input keyevent KEYCODE_CAMERA
    Write-Host "recording; stop with: .\deploy\record.ps1 -Stop -Name <name>"
    return
}

if ($Stop) {
    & adb shell input keyevent KEYCODE_CAMERA
    Start-Sleep -Seconds 3
    $before = if (Test-Path $Marker) { Get-Content $Marker } else { @() }
    $new = Listing | Where-Object { $_ -notin $before }
    & adb shell am force-stop ($Camera -split "/")[0]
    $clip = $new | Where-Object { $_ -like "VID_*.mp4" } | Select-Object -Last 1
    if (-not $clip) {
        if ($new | Where-Object { $_ -like "IMG_*" }) { throw "the camera app was in photo mode (it took a picture); record again" }
        throw "no new clip in $Dcim"
    }
    if (-not $Name) { $Name = [IO.Path]::GetFileNameWithoutExtension($clip) }
    $out = Join-Path $Root "tmp\videos\$Name.mp4"
    & adb pull "$Dcim/$clip" $out | Out-Null
    Remove-Item $Marker -ErrorAction SilentlyContinue
    Write-Host "pulled $clip -> $out"
    if (Get-Command ffprobe -ErrorAction SilentlyContinue) {
        & ffprobe -v error -select_streams v:0 -show_entries "stream=codec_name,width,height,r_frame_rate,bit_rate:format=duration" -of default=nw=1 $out
    }
    return
}

Write-Host "use -Start or -Stop"
