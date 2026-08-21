# Mirabel Voice - install from this folder.
#
# Right-click Install.ps1 and choose "Run with PowerShell", or run:
#   powershell -ExecutionPolicy Bypass -File Install.ps1
#
# It copies the app into your own profile, asks for your token, and
# starts it. Nothing here needs an administrator password.
#
# Running it again updates the app and keeps your settings and token.
param([string]$Token = "")

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$relayUrl = "__RELAY_URL__"
$target = Join-Path $env:LOCALAPPDATA "Programs\Mirabel Voice"
$appExe = Join-Path $target "MirabelVoice.exe"
$consoleExe = Join-Path $target "MirabelVoiceConsole.exe"

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }

Say ""
Say "  Mirabel Voice" "Cyan"
Say "  Speak instead of type." "DarkGray"
Say ""

$source = Join-Path $here "MirabelVoice"
if (-not (Test-Path (Join-Path $source "MirabelVoice.exe"))) {
    Say "  This script has to sit next to the MirabelVoice folder." "Red"
    Say "  Unzip the whole download, then run it from there." "Red"
    exit 1
}

# --- 1. Stop a running copy, or its files cannot be replaced ---------------
Get-Process MirabelVoice -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
Start-Sleep -Milliseconds 600

# --- 2. Copy the app -------------------------------------------------------
Say "  Copying the app..."
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item (Join-Path $source "*") $target -Recurse -Force
Say "  Copied." "Green"

# --- 3. Your token ---------------------------------------------------------
# The app owns its settings file, so it stores the token. Writing that file
# from here would overwrite the dictation key and everything else.
& $consoleExe --has-relay-token | Out-Null
$hasToken = ($LASTEXITCODE -eq 0)

if ($Token) {
    & $consoleExe --set-relay $relayUrl $Token | Out-Null
} elseif ($hasToken) {
    # Keep the token already here, and follow the relay if it moved.
    & $consoleExe --set-relay $relayUrl | Out-Null
} else {
    Say ""
    Say "  The app needs your token. Ask Tommy for it." "Yellow"
    Say "  There are no API keys to enter: they stay on our server." "DarkGray"
    $answer = Read-Host "  Token"
    if (-not $answer) { Say "  A token is needed. Run this again when you have one." "Red"; exit 1 }
    & $consoleExe --set-relay $relayUrl $answer.Trim() | Out-Null
}

Say "  Checking your token..."
$check = & $consoleExe --check-keys
if ($LASTEXITCODE -ne 0) {
    # Clear the refused token, so running this again asks for it.
    & $consoleExe --forget-relay-token | Out-Null
    Say "  $check" "Red"
    Say ""
    Say "  That token was not accepted. Check it with Tommy and run this again." "Red"
    exit 1
}
Say "  Your token works." "Green"

# --- 4. Shortcuts ----------------------------------------------------------
$shell = New-Object -ComObject WScript.Shell
function New-Launcher($path) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $appExe
    $s.WorkingDirectory = $target
    $s.Description = "Mirabel Voice"
    $s.Save()
}
New-Launcher (Join-Path ([Environment]::GetFolderPath("Desktop")) "Mirabel Voice.lnk")
New-Launcher (Join-Path ([Environment]::GetFolderPath("Startup")) "Mirabel Voice.lnk")

# --- 5. Start it -----------------------------------------------------------
Start-Process -FilePath $appExe -WorkingDirectory $target

$settings = (& $consoleExe --config).Trim()
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
