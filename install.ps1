# Mirabel Voice - install it, or update it, with one pasted line.
#
#   irm https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/install.ps1 | iex
#
# Not installed yet? Download the zip from the company shared drive
# first. This finds it in Downloads, unblocks it, unpacks it, and runs
# the installer inside - the old Properties / Unblock / Extract /
# right-click routine, with none of the clicking.
#
# Already installed? Then there is nothing to download: this fetches
# the newest release's source from this repository, swaps it into the
# installed bundle, and restarts the app. Your settings stay. The
# Python runtime is untouched, which is what keeps Smart App Control
# content. A release that changes the runtime itself is rare; when one
# comes, this says so and points back at the shared drive.
#
# This script holds no secrets, which is why it can live in a public
# repository. The relay's address travels only inside the zip, and the
# zip stays behind the shared drive's sign-in. Updates need no secret
# at all: an installed machine already has the address, and the code
# is public.
param(
    # Where the zip landed, and where work happens. Tests point these
    # somewhere else.
    [string]$DownloadsDir = "",
    [string]$WorkDir = "",
    # The installed app. Tests point these at a fake one.
    [string]$Target = "",
    [string]$PythonExe = "",
    # A release source zip already on disk, so tests skip the network.
    [string]$SourceZip = ""
)

$ErrorActionPreference = "Stop"
$driveLink = "https://drive.google.com/drive/folders/0AL2zqxan1Ec6Uk9PVA"
$releaseApi = "https://api.github.com/repos/mirabeltech/mirabel-voice/releases/latest"
$archiveBase = "https://github.com/mirabeltech/mirabel-voice/archive/refs/tags"

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }

function Find-Zip($dirs) {
    $dirs | Where-Object { $_ -and (Test-Path $_) } | ForEach-Object {
        Get-ChildItem (Join-Path $_ "MirabelVoice-*.zip") -ErrorAction SilentlyContinue
    } | Sort-Object LastWriteTime | Select-Object -Last 1
}

function Read-Version($text) {
    # A version out of a file name or a folder name, or $null.
    if ($text -match "([0-9]+\.[0-9]+(\.[0-9]+)?)") { return [version]$Matches[1] }
    return $null
}

Say ""
Say "  Mirabel Voice" "Cyan"
Say "  Speak instead of type." "DarkGray"
Say ""

if (-not $Target) { $Target = Join-Path $env:LOCALAPPDATA "Programs\Mirabel Voice" }
if (-not $PythonExe) { $PythonExe = Join-Path $Target "python\python.exe" }
if (-not $WorkDir) { $WorkDir = Join-Path $env:TEMP "MirabelVoiceInstall" }
$sitePackages = Join-Path $Target "python\Lib\site-packages"

if (-not $DownloadsDir) {
    # OneDrive moves the Downloads folder; the registry knows where it went.
    $shell = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    try { $DownloadsDir = (Get-ItemProperty $shell)."{374DE290-123F-4565-9164-39C4925E467B}" } catch {}
    if (-not $DownloadsDir) { $DownloadsDir = Join-Path $env:USERPROFILE "Downloads" }
}
$searched = @($DownloadsDir, (Get-Location).Path)

# --- Which job is this? -----------------------------------------------------
# A bundle that is already installed updates from the public repository:
# no download, no zip. The zip flow runs for a first install, and for a
# downloaded zip newer than what is installed, which is how a release
# that changes the runtime itself arrives.
$bundled = Test-Path (Join-Path $Target "python\pythonw.exe")
$packaged = Test-Path (Join-Path $Target "MirabelVoice.exe")
$zip = Find-Zip $searched

$installedVersion = $null
if ($bundled) {
    $distInfo = Get-ChildItem $sitePackages -Directory -Filter "mirabel_voice-*.dist-info" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($distInfo) { $installedVersion = Read-Version $distInfo.Name }
}

$job = "install"
if ($bundled) {
    $job = "update"
    if ($zip) {
        $zipVersion = Read-Version $zip.Name
        if (-not $installedVersion -or ($zipVersion -and $zipVersion -gt $installedVersion)) {
            $job = "install"  # the downloaded zip is ahead: use it
        }
    }
} elseif ($packaged -and -not $zip) {
    Say "  This machine runs the packaged program, which updates from the" "Yellow"
    Say "  zip. Download the newest one from the shared drive, then paste" "Yellow"
    Say "  the same line again:" "Yellow"
    Say "  $driveLink" "DarkGray"
    return
}

# --- Update: fetch the newest source and swap it in -------------------------
if ($job -eq "update") {
    if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force }
    New-Item -ItemType Directory -Force $WorkDir | Out-Null

    if (-not $SourceZip) {
        Say "  Checking the newest release..."
        $tag = (Invoke-RestMethod $releaseApi).tag_name
        $SourceZip = Join-Path $WorkDir "source.zip"
        Invoke-WebRequest "$archiveBase/$tag.zip" -OutFile $SourceZip
    }
    Expand-Archive $SourceZip (Join-Path $WorkDir "source") -Force

    $newPackage = Get-ChildItem (Join-Path $WorkDir "source") -Recurse -Directory -Filter "mirabel_voice" |
        Where-Object { Test-Path (Join-Path $_.FullName "__init__.py") } | Select-Object -First 1
    $pyproject = Get-ChildItem (Join-Path $WorkDir "source") -Recurse -Filter "pyproject.toml" | Select-Object -First 1
    if (-not $newPackage -or -not $pyproject) {
        Say "  The release download looks wrong; nothing was changed." "Red"
        return
    }
    # The version the build tools read. __version__ in the package has
    # drifted before; pyproject.toml is what names the release.
    $newVersion = Read-Version ((Get-Content $pyproject.FullName | Where-Object { $_ -match '^version' }) -join "")

    if ($installedVersion -and $newVersion -and $newVersion -le $installedVersion) {
        Say "  Already up to date (version $installedVersion)." "Green"
        Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
        return
    }

    Say "  Updating $(if ($installedVersion) { "$installedVersion " })to $newVersion..."
    Get-Process MirabelVoice, pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like "$Target*" } | Stop-Process -Force -Confirm:$false
    Start-Sleep -Milliseconds 600

    $installed = Join-Path $sitePackages "mirabel_voice"
    $backup = Join-Path $WorkDir "previous"
    Move-Item $installed $backup
    Copy-Item $newPackage.FullName $installed -Recurse

    # The proof: the updated app must still import and answer. A release
    # that needs a new library fails here, and the old code goes back.
    # Stop-on-error rests for a moment: a traceback on stderr must land
    # in the verdict below, not kill the script between swap and restore.
    $keep = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExe -m mirabel_voice --config *> $null
    $healthy = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $keep
    if ($healthy) {
        if ($distInfo -and $newVersion) {
            # Keep the version marker honest, so the next run compares right.
            Rename-Item $distInfo.FullName "mirabel_voice-$newVersion.dist-info"
        }
        Say "  Updated. Starting Mirabel Voice..." "Green"
    } else {
        Remove-Item $installed -Recurse -Force
        Move-Item $backup $installed
        Say "  This release needs more than new code, so the old version" "Red"
        Say "  was kept. Download the new zip from the shared drive, then" "Red"
        Say "  paste the same line again:" "Red"
        Say "  $driveLink" "DarkGray"
    }

    try {
        Start-Process -FilePath (Join-Path $Target "python\pythonw.exe") `
            -ArgumentList "-m", "mirabel_voice" -WorkingDirectory $Target
    } catch {
        Say "  Could not restart the app - open Mirabel Voice from the Start menu." "Yellow"
    }
    Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
    return
}

# --- Install: find the zip you downloaded ------------------------------------
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

# Unblocking here is the tick in the zip's Properties dialog, done for you.
Unblock-File $zip.FullName
if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force }
Say "  Unpacking (half a minute)..."
Expand-Archive $zip.FullName $WorkDir -Force

$installer = Get-ChildItem $WorkDir -Recurse -Filter "Install.ps1" | Select-Object -First 1
if (-not $installer) {
    Say "  That zip has no installer inside. Is it the right download?" "Red"
    Say "  The one to get is at $driveLink" "Red"
    return
}

if ($ExecutionContext.SessionState.LanguageMode -ne "FullLanguage") {
    # Smart App Control can hold PowerShell in a restricted mode that
    # cannot make shortcuts. Warn now rather than fail mysteriously.
    Say "  This machine restricts PowerShell. If the install stops at" "Yellow"
    Say "  an error about shortcuts, tell Tommy." "Yellow"
}
& powershell -NoProfile -ExecutionPolicy Bypass -File $installer.FullName
$result = $LASTEXITCODE

Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
if ($result -ne 0) { Say "  The install did not finish. The message above says why." "Red" }
