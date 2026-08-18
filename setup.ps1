# Mirabel Voice setup.
# Run this once after you download the code:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# The script is safe to run again at any time.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host ""
Write-Host "Mirabel Voice setup" -ForegroundColor Cyan
Write-Host "-------------------"

# 1. Find a real Python 3.10+. On a fresh Windows PC, "python" can be a
# Microsoft Store stub that prints nothing and installs nothing.
$installMessage = "Python 3.10 or newer is not installed. Install it from python.org (check 'Add python.exe to PATH'), then run this script again."
$version = ""
try { $version = & python -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))" 2>$null } catch {}
if (-not $version) {
    Write-Host $installMessage -ForegroundColor Red
    exit 1
}
$parts = $version.Trim().Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    Write-Host "Found Python $version, but $installMessage" -ForegroundColor Red
    exit 1
}
Write-Host "Found Python $version"

# 2. Create the private environment for the app (first run only).
$venv = Join-Path $root ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating the app environment..."
    & python -m venv $venv
    if (-not (Test-Path $venvPython)) {
        Write-Host "The environment was not created. $installMessage" -ForegroundColor Red
        exit 1
    }
    & $venvPython -m pip install --quiet --upgrade pip
}

# 3. Install the app.
Write-Host "Installing Mirabel Voice (this can take a minute)..."
& $venvPython -m pip install --quiet -e $root
Write-Host "Installed." -ForegroundColor Green

# 4. Store the API keys, if they are not stored yet.
$configDir = Join-Path $env:APPDATA "MirabelVoice"
$keysFile = Join-Path $configDir "keys.json"
if (Test-Path $keysFile) {
    Write-Host "API keys are already stored. Delete $keysFile to enter new ones."
} else {
    Write-Host ""
    Write-Host "The app needs the two Mirabel API keys. Ask Tommy for them."
    $openaiKey = Read-Host "Paste the OpenAI key"
    $anthropicKey = Read-Host "Paste the Anthropic key"
    if (-not $openaiKey -or -not $anthropicKey) {
        Write-Host "Both keys are needed. Run the script again when you have them." -ForegroundColor Red
        exit 1
    }
    New-Item -ItemType Directory -Force $configDir | Out-Null
    @{ openai_api_key = $openaiKey; anthropic_api_key = $anthropicKey } |
        ConvertTo-Json | Out-File -FilePath $keysFile -Encoding utf8
    Write-Host "Keys stored in $keysFile" -ForegroundColor Green
}

# 5. Create a launcher on the Desktop and offer a start-with-Windows shortcut.
$pythonw = Join-Path $venv "Scripts\pythonw.exe"
$shell = New-Object -ComObject WScript.Shell

function New-Launcher($path) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "-m mirabel_voice"
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = "Mirabel Voice - hold Ctrl+Win and speak"
    $shortcut.Save()
}

$desktop = [Environment]::GetFolderPath("Desktop")
New-Launcher (Join-Path $desktop "Mirabel Voice.lnk")
Write-Host "A 'Mirabel Voice' shortcut is on your Desktop."

$answer = Read-Host "Start Mirabel Voice automatically when Windows starts? (y/n)"
$startupLink = Join-Path ([Environment]::GetFolderPath("Startup")) "Mirabel Voice.lnk"
if ($answer -eq "y") {
    New-Launcher $startupLink
    Write-Host "Done. It will start with Windows." -ForegroundColor Green
} elseif (Test-Path $startupLink) {
    Remove-Item $startupLink -Confirm:$false
    Write-Host "The start-with-Windows shortcut was removed."
}

Write-Host ""
Write-Host "Setup is complete." -ForegroundColor Cyan
Write-Host "Double-click 'Mirabel Voice' on your Desktop, then:"
Write-Host "  1. Click into any text box."
Write-Host "  2. Hold Ctrl+Win and speak."
Write-Host "  3. Release. Your words appear."
