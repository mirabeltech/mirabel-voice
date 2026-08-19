# Mirabel Voice setup.
# Run this once:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# It is safe to run again at any time.

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

# --- 3. Keys ---------------------------------------------------------------
$configDir = & $py -c "from mirabel_voice.config import config_dir; print(config_dir())"
$keysFile = Join-Path $configDir "keys.json"

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

if (-not (Test-Path $keysFile)) { Save-Keys }

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
Say "  Click into any text box, hold $key, and speak." "Cyan"
Say "  Let go, and your words are tidied up."
Say ""
Say "  Esc          throw away what you are saying"
Say "  Shift+Alt+Z  paste the last dictation again"
Say ""
