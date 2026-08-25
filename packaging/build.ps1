# Build the packaged installer on this computer.
#
# Run it from anywhere:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# The result is dist\MirabelVoiceSetup-<version>.exe.
#
# You need Inno Setup 6.3 or newer. Install it once:
#   winget install JRSoftware.InnoSetup
#
# The installer asks each person for one relay token, so the build needs
# the relay's address to bake in. It comes from -RelayUrl, or the
# MIRABEL_VOICE_RELAY_URL environment variable, or a relay.json in the
# repository root. The address is not a secret; the tokens are.
param(
    [string]$RelayUrl = "",
    [string]$GoogleClientId = "",
    [string]$GoogleClientSecret = ""
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path $here -Parent

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }

# --- 1. Python -------------------------------------------------------------
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Say "  No .venv here. Run setup.ps1 first." "Red"
    exit 1
}

Say ""
Say "  Building Mirabel Voice" "Cyan"
Say ""

# --- The relay address -----------------------------------------------------
if (-not $RelayUrl -and $env:MIRABEL_VOICE_RELAY_URL) { $RelayUrl = $env:MIRABEL_VOICE_RELAY_URL }
$relayFile = Join-Path $root "relay.json"
if (Test-Path $relayFile) {
    $relayInfo = Get-Content $relayFile -Raw | ConvertFrom-Json
    if (-not $RelayUrl) { $RelayUrl = $relayInfo.relay_url }
    # The Google sign-in client rides beside the relay address; neither is
    # a secret, and both stay out of the repository the same way.
    if (-not $GoogleClientId) { $GoogleClientId = $relayInfo.google_client_id }
    if (-not $GoogleClientSecret) { $GoogleClientSecret = $relayInfo.google_client_secret }
}
if (-not $RelayUrl) {
    Say "  No relay address. The installer would have nowhere to send dictation." "Red"
    Say "  Pass one:  packaging/build.ps1 -RelayUrl https://<the relay address>" "Red"
    Say "  Or run:    python scripts/setup_relay.py   to see it." "Red"
    exit 1
}
Say "  Relay $RelayUrl" "DarkGray"

# --- 2. Tests --------------------------------------------------------------
# A broken build must never reach anybody's computer.
Say "  Running the tests..."
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { Say "  Tests failed. Nothing was built." "Red"; exit 1 }

# --- 3. Build inputs -------------------------------------------------------
& $py -m pip install --quiet --disable-pip-version-check pyinstaller
$version = (& $py (Join-Path $here "prepare.py")).Trim()
Say "  Version $version" "DarkGray"

# --- 4. The program --------------------------------------------------------
Say "  Packing the program (this takes a minute)..."
Push-Location $root
try {
    & $py -m PyInstaller --noconfirm --clean --log-level WARN (Join-Path $here "mirabel_voice.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
} finally { Pop-Location }

# --- 5. The installer ------------------------------------------------------
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($iscc) {
    $isccPath = $iscc.Source
} else {
    # winget installs Inno per-user by default, which is the last one.
    $isccPath = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $isccPath) {
    Say "  Inno Setup is missing. Install it with:" "Red"
    Say "    winget install JRSoftware.InnoSetup" "Red"
    exit 1
}

# --- 5a. The zip ------------------------------------------------------------
# Smart App Control refuses unsigned setup executables, and offers no way
# past it (see issue #35). The app's own binaries are not refused, so this
# is the same install without a setup executable in it.
Say "  Making the zip..."
$staging = Join-Path $root "dist\zip"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Force $staging | Out-Null
Copy-Item (Join-Path $root "dist\MirabelVoice") $staging -Recurse
$installer = Get-Content (Join-Path $here "Install.ps1") -Raw
$installer = $installer.Replace("__RELAY_URL__", $RelayUrl)
$installer = $installer.Replace("__GOOGLE_CLIENT_ID__", "$GoogleClientId")
$installer = $installer.Replace("__GOOGLE_CLIENT_SECRET__", "$GoogleClientSecret")
$installer | Out-File -FilePath (Join-Path $staging "Install.ps1") -Encoding utf8
Copy-Item (Join-Path $here "Install.cmd") $staging
$zip = Join-Path $root "dist\MirabelVoice-$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zip
Remove-Item $staging -Recurse -Force
Say "  Zipped." "Green"

Say "  Making the installer..."
& $isccPath "/Q" "/DAppVersion=$version" "/DRelayUrl=$RelayUrl" (Join-Path $here "installer.iss")
if ($LASTEXITCODE -ne 0) { Say "  Inno Setup failed." "Red"; exit 1 }

$setup = Join-Path $root "dist\MirabelVoiceSetup-$version.exe"
$size = [math]::Round((Get-Item $setup).Length / 1MB, 1)
$zipSize = [math]::Round((Get-Item $zip).Length / 1MB, 1)

Say ""
Say "  Done." "Green"
Say "    $setup ($size MB)"
Say "    $zip ($zipSize MB)   for machines with Smart App Control on"
Say ""
