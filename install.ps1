# Mirabel Voice - install from the zip in your Downloads folder.
#
# Download the zip from the company shared drive, then paste this into
# PowerShell:
#
#   irm https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/install.ps1 | iex
#
# It finds the zip, unblocks it, unpacks it, and runs the installer
# inside - the same work as the old Properties / Unblock / Extract /
# right-click routine, with none of the clicking. Download a newer zip
# and paste the same line again to update; your settings stay.
#
# This script holds no secrets, which is why it can live in a public
# repository. The relay's address travels only inside the zip, and the
# zip stays behind the shared drive's sign-in.
param(
    # Where the zip landed. Tests point these somewhere else.
    [string]$DownloadsDir = "",
    [string]$WorkDir = ""
)

$ErrorActionPreference = "Stop"
$driveLink = "https://drive.google.com/drive/folders/0AL2zqxan1Ec6Uk9PVA"

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }

function Find-Zip($dirs) {
    $dirs | Where-Object { $_ -and (Test-Path $_) } | ForEach-Object {
        Get-ChildItem (Join-Path $_ "MirabelVoice-*.zip") -ErrorAction SilentlyContinue
    } | Sort-Object LastWriteTime | Select-Object -Last 1
}

Say ""
Say "  Mirabel Voice" "Cyan"
Say "  Speak instead of type." "DarkGray"
Say ""

# --- 1. Find the zip you downloaded ----------------------------------------
if (-not $DownloadsDir) {
    # OneDrive moves the Downloads folder; the registry knows where it went.
    $shell = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    try { $DownloadsDir = (Get-ItemProperty $shell)."{374DE290-123F-4565-9164-39C4925E467B}" } catch {}
    if (-not $DownloadsDir) { $DownloadsDir = Join-Path $env:USERPROFILE "Downloads" }
}
$searched = @($DownloadsDir, (Get-Location).Path)

$zip = Find-Zip $searched
if (-not $zip) {
    Say "  No MirabelVoice zip in $DownloadsDir yet." "Yellow"
    Say "  Get it from the shared drive - opening the page now:" "Yellow"
    Say "  $driveLink" "DarkGray"
    Start-Process $driveLink
    Say ""
    Say "  Waiting here for the download. Ctrl+C stops."
    $deadline = (Get-Date).AddMinutes(10)
    while (-not $zip -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        $zip = Find-Zip $searched
    }
    if (-not $zip) {
        Say "  Nothing arrived. Download the zip, then paste the same line again." "Red"
        return
    }
    Start-Sleep -Seconds 1
}
Say "  Found $($zip.Name)."

# --- 2. Unblock and unpack --------------------------------------------------
# Unblocking here is the tick in the zip's Properties dialog, done for you.
Unblock-File $zip.FullName
if (-not $WorkDir) { $WorkDir = Join-Path $env:TEMP "MirabelVoiceInstall" }
if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force }
Say "  Unpacking (half a minute)..."
Expand-Archive $zip.FullName $WorkDir -Force

$installer = Get-ChildItem $WorkDir -Recurse -Filter "Install.ps1" | Select-Object -First 1
if (-not $installer) {
    Say "  That zip has no installer inside. Is it the right download?" "Red"
    Say "  The one to get is at $driveLink" "Red"
    return
}

# --- 3. Run the installer from the zip ---------------------------------------
if ($ExecutionContext.SessionState.LanguageMode -ne "FullLanguage") {
    # Smart App Control can hold PowerShell in a restricted mode that
    # cannot make shortcuts. Warn now rather than fail mysteriously.
    Say "  This machine restricts PowerShell. If the install stops at" "Yellow"
    Say "  an error about shortcuts, tell Tommy." "Yellow"
}
& powershell -NoProfile -ExecutionPolicy Bypass -File $installer.FullName
$result = $LASTEXITCODE

# --- 4. Tidy up ---------------------------------------------------------------
Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
if ($result -ne 0) { Say "  The install did not finish. The message above says why." "Red" }
