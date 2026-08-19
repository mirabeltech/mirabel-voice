# Mirabel Voice - one command install.
#
# Paste this into PowerShell:
#   iwr -useb https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/install.ps1 | iex
#
# It downloads the app, sets it up, and starts it. Running it again
# updates the app to the latest version.

$ErrorActionPreference = "Stop"
$repo = "https://github.com/mirabeltech/mirabel-voice.git"
$home_ = Join-Path $env:LOCALAPPDATA "MirabelVoice\app"

function Say($t, $c = "Gray") { Write-Host $t -ForegroundColor $c }

Say ""
Say "  Mirabel Voice" "Cyan"
Say ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Say "  Git is missing. Install it from git-scm.com, then run this again." "Red"
    exit 1
}

if (Test-Path (Join-Path $home_ ".git")) {
    Say "  Updating..."
    git -C $home_ pull --quiet
} else {
    Say "  Downloading..."
    New-Item -ItemType Directory -Force (Split-Path $home_) | Out-Null
    git clone --quiet $repo $home_
}

& powershell -ExecutionPolicy Bypass -File (Join-Path $home_ "setup.ps1")
