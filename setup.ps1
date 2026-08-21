# Mirabel Voice setup.
# Run this once:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# It is safe to run again at any time.
#
# Pass -RelayUrl to set this machine up against the relay, which holds the
# provider keys. Without it the machine talks to the providers directly and
# needs both keys, which is the development mode.
param([string]$RelayUrl = "")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }

Say ""
Say "  Mirabel Voice" "Cyan"
Say "  Speak instead of type." "DarkGray"
Say ""

# --- 1. Python -------------------------------------------------------------
$needPython = "Python 3.10 or newer is missing. Install it from python.org and tick 'Add python.exe to PATH', then run this again."
$version = ""
try { $version = & python -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))" 2>$null } catch {}
if (-not $version) { Say $needPython "Red"; exit 1 }
$parts = $version.Trim().Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    Say "Found Python $version. $needPython" "Red"; exit 1
}

# --- 2. Install ------------------------------------------------------------
$venv = Join-Path $root ".venv"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    Say "  Preparing (about a minute)..."
    & python -m venv $venv
    if (-not (Test-Path $py)) { Say "The setup could not start. $needPython" "Red"; exit 1 }
    & $py -m pip install --quiet --disable-pip-version-check --upgrade pip
}
& $py -m pip install --quiet --disable-pip-version-check -e $root
Say "  Installed." "Green"

# --- 3. Credentials --------------------------------------------------------
$configDir = & $py -c "from mirabel_voice.config import config_dir; print(config_dir())"
$keysFile = Join-Path $configDir "keys.json"

# A relay machine holds one token and no provider keys. The address is not
# secret and may be prepared for the person; the token is theirs alone.
$relayFile = Join-Path $root "relay.json"
if (-not $RelayUrl -and $env:MIRABEL_VOICE_RELAY_URL) { $RelayUrl = $env:MIRABEL_VOICE_RELAY_URL }
if (-not $RelayUrl -and (Test-Path $relayFile)) {
    $RelayUrl = (Get-Content $relayFile -Raw | ConvertFrom-Json).relay_url
}

function Save-RelayToken {
    Say ""
    Say "  The app needs your relay token. Ask Tommy for it." "Yellow"
    $token = Read-Host "  Relay token"
    if (-not $token) { Say "  A token is needed. Run this again when you have one." "Red"; exit 1 }
    $token = $token.Trim()
    & $py (Join-Path $root "scripts\set_relay.py") --url $RelayUrl --token $token | Out-Null
    if ($LASTEXITCODE -ne 0) { Say "  The token could not be saved." "Red"; exit 1 }
}

function Save-Keys {
    Say ""
    Say "  The app needs two keys. Ask Tommy for them." "Yellow"
    $a = Read-Host "  OpenAI key"
    $b = Read-Host "  Anthropic key"
    if (-not $a -or -not $b) { Say "  Both keys are needed. Run this again when you have them." "Red"; exit 1 }
    New-Item -ItemType Directory -Force $configDir | Out-Null
    @{ openai_api_key = $a.Trim(); anthropic_api_key = $b.Trim() } |
        ConvertTo-Json | Out-File -FilePath $keysFile -Encoding utf8
}

if ($RelayUrl) {
    # Keep the address current even for a machine that already has a token.
    & $py (Join-Path $root "scripts\set_relay.py") --url $RelayUrl | Out-Null
    $haveToken = & $py -c "from mirabel_voice.config import Config; print('yes' if Config.load().relay_token else 'no')"
    if ($haveToken.Trim() -ne "yes") { Save-RelayToken }

    Say "  Checking the relay..."
    $check = & $py (Join-Path $root "scripts\check_keys.py")
    if ($LASTEXITCODE -ne 0) {
        Say "  $check" "Red"
        Say ""
        Say "  Let's enter the token again." "Yellow"
        Save-RelayToken
        $check = & $py (Join-Path $root "scripts\check_keys.py")
        if ($LASTEXITCODE -ne 0) { Say "  $check" "Red"; Say "  Ask Tommy to check the token." "Red"; exit 1 }
    }
    Say "  The relay works. No keys on this machine." "Green"
} else {
    if (-not (Test-Path $keysFile)) {
        # Look for a keys file the administrator has already prepared, so
        # nobody has to type a key. First one found wins.
        $sources = @(
            (Join-Path $root "keys.json"),          # shipped beside this script
            $env:MIRABEL_VOICE_KEYS                 # a path or network share
        ) | Where-Object { $_ -and (Test-Path $_) }

        if ($sources) {
            New-Item -ItemType Directory -Force $configDir | Out-Null
            Copy-Item $sources[0] $keysFile -Force
            Say "  Keys found. Nothing to type." "Green"
        } else {
            Save-Keys
        }
    }

    Say "  Checking the keys..."
    $check = & $py (Join-Path $root "scripts\check_keys.py")
    if ($LASTEXITCODE -ne 0) {
        Say "  $check" "Red"
        Say ""
        Say "  Let's enter them again." "Yellow"
        Remove-Item $keysFile -Force -Confirm:$false
        Save-Keys
        $check = & $py (Join-Path $root "scripts\check_keys.py")
        if ($LASTEXITCODE -ne 0) { Say "  $check" "Red"; Say "  Ask Tommy to check the keys." "Red"; exit 1 }
    }
    Say "  Keys work." "Green"
}

# --- 4. Your key -----------------------------------------------------------
Say ""
Say "  Your dictation key is Insert." "Cyan"
$answer = Read-Host "  Press Enter to keep it, or type C to choose another key"
if ($answer -match "^[Cc]") { & $py (Join-Path $root "scripts\pick_hotkey.py") }

# --- 5. Shortcuts ----------------------------------------------------------
$pythonw = Join-Path $venv "Scripts\pythonw.exe"
$shell = New-Object -ComObject WScript.Shell
function New-Launcher($path) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $pythonw; $s.Arguments = "-m mirabel_voice"
    $s.WorkingDirectory = $root; $s.Description = "Mirabel Voice"
    $s.Save()
}
New-Launcher (Join-Path ([Environment]::GetFolderPath("Desktop")) "Mirabel Voice.lnk")
$startup = Join-Path ([Environment]::GetFolderPath("Startup")) "Mirabel Voice.lnk"
New-Launcher $startup

# --- 6. Start it -----------------------------------------------------------
Get-Process pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$root*" } | Stop-Process -Force -Confirm:$false
Start-Sleep -Milliseconds 600
Start-Process -FilePath $pythonw -ArgumentList "-m","mirabel_voice" -WorkingDirectory $root

$key = & $py -c "from mirabel_voice.config import Config; print(Config.load().hotkey.replace(chr(95),chr(32)).title())"

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
