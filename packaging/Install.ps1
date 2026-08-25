# Mirabel Voice - install from this folder.
#
# Double-click Install.cmd, or right-click Install.ps1 and choose
# "Run with PowerShell" (behind "Show more options" on Windows 11), or run:
#   powershell -ExecutionPolicy Bypass -File Install.ps1
#
# It copies the app into your own profile, asks for your token, and starts
# it. Nothing here needs an administrator password.
#
# Running it again updates the app and keeps your settings and your token.
#
# Two downloads use this script. One holds a packaged program; the other
# holds Python and the source, for computers whose Smart App Control
# refuses unsigned programs. The layout in the folder says which is which.
param([string]$Token = "")

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$relayUrl = "__RELAY_URL__"
$googleClientId = "__GOOGLE_CLIENT_ID__"
$googleClientSecret = "__GOOGLE_CLIENT_SECRET__"
# With the Google client in the download, there is no token page at all:
# the app signs the person in with their work account on first start.
$googleMode = $googleClientId -and $googleClientSecret -and
    ($googleClientId -notlike "__GOOGLE*") -and ($googleClientSecret -notlike "__GOOGLE*")
$target = Join-Path $env:LOCALAPPDATA "Programs\Mirabel Voice"

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }

Say ""
Say "  Mirabel Voice" "Cyan"
Say "  Speak instead of type." "DarkGray"
Say ""

$packaged = Join-Path $here "MirabelVoice\MirabelVoice.exe"
$bundled = Join-Path $here "python\pythonw.exe"
if (Test-Path $packaged) {
    $kind = "packaged"
} elseif (Test-Path $bundled) {
    $kind = "bundled"
} else {
    Say "  This script has to sit next to the app folder." "Red"
    Say "  Unzip the whole download, then run it from there." "Red"
    exit 1
}

# --- 1. Stop a running copy, or its files cannot be replaced ---------------
Get-Process MirabelVoice, pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$target*" } | Stop-Process -Force -Confirm:$false
Start-Sleep -Milliseconds 600

# --- 2. Copy the app -------------------------------------------------------
Say "  Copying the app..."
New-Item -ItemType Directory -Force $target | Out-Null
if ($kind -eq "packaged") {
    Copy-Item (Join-Path $here "MirabelVoice\*") $target -Recurse -Force
    $launch = Join-Path $target "MirabelVoice.exe"
    $launchArgs = @()
    $console = Join-Path $target "MirabelVoiceConsole.exe"
    $consoleArgs = @()
} else {
    Copy-Item (Join-Path $here "python") $target -Recurse -Force
    $launch = Join-Path $target "python\pythonw.exe"
    $launchArgs = @("-m", "mirabel_voice")
    $console = Join-Path $target "python\python.exe"
    $consoleArgs = @("-m", "mirabel_voice")
}
Say "  Copied." "Green"

# --- 3. Your sign-in, or your token ----------------------------------------
# The app owns its settings file, so the app stores the credential. Writing
# that file from here would overwrite the dictation key and everything else.
if ($googleMode) {
    & $console @consoleArgs --set-relay $relayUrl | Out-Null
    & $console @consoleArgs --set-google $googleClientId $googleClientSecret | Out-Null
    Say ""
    Say "  No token to enter: you sign in with your Mirabel Google account." "DarkGray"
    Say "  Your browser opens once, the first time the app starts." "DarkGray"
} else {
    & $console @consoleArgs --has-relay-token | Out-Null
    $hasToken = ($LASTEXITCODE -eq 0)

    if ($Token) {
        & $console @consoleArgs --set-relay $relayUrl $Token | Out-Null
    } elseif ($hasToken) {
        # Keep the token already here, and follow the relay if it moved.
        & $console @consoleArgs --set-relay $relayUrl | Out-Null
    } else {
        Say ""
        Say "  The app needs your token. Ask Tommy for it." "Yellow"
        Say "  There are no API keys to enter: they stay on our server." "DarkGray"
        $answer = Read-Host "  Token"
        if (-not $answer) { Say "  A token is needed. Run this again when you have one." "Red"; exit 1 }
        & $console @consoleArgs --set-relay $relayUrl $answer.Trim() | Out-Null
    }

    Say "  Checking your token..."
    $check = & $console @consoleArgs --check-keys
    if ($LASTEXITCODE -ne 0) {
        # Clear the refused token, so that running this again asks for one.
        & $console @consoleArgs --forget-relay-token | Out-Null
        Say "  $check" "Red"
        Say ""
        Say "  That token was not accepted. Check it with Tommy and run this again." "Red"
        exit 1
    }
    Say "  Your token works." "Green"
}

# --- 4. Shortcuts ----------------------------------------------------------
$shell = New-Object -ComObject WScript.Shell
function New-Launcher($path) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $launch
    $s.Arguments = ($launchArgs -join " ")
    $s.WorkingDirectory = $target
    $s.Description = "Mirabel Voice"
    $s.Save()
}
New-Launcher (Join-Path ([Environment]::GetFolderPath("Desktop")) "Mirabel Voice.lnk")
New-Launcher (Join-Path ([Environment]::GetFolderPath("Startup")) "Mirabel Voice.lnk")

# --- 5. Start it -----------------------------------------------------------
if ($launchArgs.Count) {
    Start-Process -FilePath $launch -ArgumentList $launchArgs -WorkingDirectory $target
} else {
    Start-Process -FilePath $launch -WorkingDirectory $target
}

$settings = (& $console @consoleArgs --config).Trim()
$key = "Insert"
if (Test-Path $settings) {
    $saved = (Get-Content $settings -Raw | ConvertFrom-Json).hotkey
    if ($saved) { $key = (Get-Culture).TextInfo.ToTitleCase($saved.Replace("_", " ")) }
}

Say ""
Say "  Ready. Mirabel Voice is running and starts with Windows." "Green"
Say ""
Say "  Click into any text box, then:" "Cyan"
Say ""
Say "    Press $key    start listening"
Say "    Speak"
Say "    Press $key    finish, and your words are tidied up"
Say ""
Say "  Esc          throw away what you are saying"
Say "  Shift+Alt+Z  paste the last dictation again"
Say ""
