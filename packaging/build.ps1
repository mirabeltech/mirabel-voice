# Build the packaged installer on this computer.
#
# Run it from anywhere:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# The result is dist\MirabelVoiceSetup-<version>.exe.
#
# You need Inno Setup 6.3 or newer. Install it once:
#   winget install JRSoftware.InnoSetup

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
    $isccPath = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $isccPath) {
    Say "  Inno Setup is missing. Install it with:" "Red"
    Say "    winget install JRSoftware.InnoSetup" "Red"
    exit 1
}

Say "  Making the installer..."
& $isccPath "/Q" "/DAppVersion=$version" (Join-Path $here "installer.iss")
if ($LASTEXITCODE -ne 0) { Say "  Inno Setup failed." "Red"; exit 1 }

$setup = Join-Path $root "dist\MirabelVoiceSetup-$version.exe"
$size = [math]::Round((Get-Item $setup).Length / 1MB, 1)

Say ""
Say "  Done. $setup ($size MB)" "Green"
Say ""
