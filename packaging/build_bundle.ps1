# Build the Python bundle: the download for a computer whose Smart App
# Control refuses unsigned programs (see issue #35).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_bundle.ps1 -RelayUrl https://...
#
# Everything executable in the result is signed by the Python Software
# Foundation. Our own code ships as source, which Windows is happy to run
# through an interpreter it already trusts. No certificate is involved.
param(
    [string]$RelayUrl = "",
    [string]$GoogleClientId = "",
    [string]$GoogleClientSecret = "",
    [string]$PythonVersion = "3.12.10"
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path $here -Parent

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Say "  No .venv here. Run setup.ps1 first." "Red"; exit 1 }

Say ""
Say "  Building the Mirabel Voice bundle" "Cyan"
Say ""

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
    Say "  No relay address. Pass -RelayUrl https://<the relay address>" "Red"
    exit 1
}
Say "  Relay $RelayUrl" "DarkGray"

Say "  Running the tests..."
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { Say "  Tests failed. Nothing was built." "Red"; exit 1 }

$version = (& $py -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])").Trim()
Say "  Version $version" "DarkGray"

# --- 1. Python itself ------------------------------------------------------
# The official embeddable build. Downloaded once and kept, because it is
# 11 MB and never changes for a given version.
$cache = Join-Path $root "dist\cache"
New-Item -ItemType Directory -Force $cache | Out-Null
$embed = Join-Path $cache "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $embed)) {
    Say "  Downloading Python $PythonVersion..."
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $embed
}

$staging = Join-Path $root "dist\bundle"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Force $staging | Out-Null
$pythonDir = Join-Path $staging "python"
Expand-Archive -Path $embed -DestinationPath $pythonDir

$signature = Get-AuthenticodeSignature (Join-Path $pythonDir "python.exe")
Say "  python.exe signed by: $($signature.SignerCertificate.Subject -replace '^CN=([^,]+).*','$1') [$($signature.Status)]" "DarkGray"
if ($signature.Status -ne "Valid") {
    Say "  That signature is the whole point of this bundle. Stopping." "Red"
    exit 1
}

# The embeddable build ignores site-packages until this line is uncommented.
# DLLs holds Tkinter, added below, and is not on the path by default.
$pth = Get-ChildItem $pythonDir -Filter "python*._pth" | Select-Object -First 1
$lines = (Get-Content $pth.FullName) -replace '^#\s*import site', 'import site'
if ($lines -notcontains "DLLs") { $lines = @("DLLs") + $lines }
$lines | Set-Content $pth.FullName -Encoding ascii

# --- 1a. Tkinter -----------------------------------------------------------
# Neither the embeddable build nor the NuGet package carries Tkinter, and
# the status panel needs it. Take it from the full Python that made the
# .venv, so the version always matches, and keep the same folder layout:
# Tcl finds its own scripts at ..\tcl relative to the DLL.
$source = (& $py -c "import sys;print(sys.base_prefix)").Trim()
$tkFiles = @("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll")
$missing = $tkFiles | Where-Object { -not (Test-Path (Join-Path $source "DLLs\$_")) }
if ($missing -or -not (Test-Path (Join-Path $source "tcl"))) {
    Say "  Tkinter is missing from $source" "Red"
    Say "  The status panel needs it. Install Python $PythonVersion from" "Red"
    Say "  python.org with the tcl/tk option on, then rebuild the .venv." "Red"
    exit 1
}
$dllDir = Join-Path $pythonDir "DLLs"
New-Item -ItemType Directory -Force $dllDir | Out-Null
foreach ($file in $tkFiles) {
    $from = Join-Path $source "DLLs\$file"
    # Every binary in this bundle is signed, or the bundle has no point.
    $sig = Get-AuthenticodeSignature $from
    if ($sig.Status -ne "Valid") {
        Say "  $file is not validly signed ($($sig.Status)). Stopping." "Red"
        exit 1
    }
    Copy-Item $from $dllDir
}
# Only the script libraries Tk actually loads. The rest of that folder is
# nmake files, Tix, and DDE, which would add megabytes for nothing.
# Both destinations are made first: Copy-Item renames the source when the
# destination folder does not already exist.
$tclDir = Join-Path $pythonDir "tcl"
New-Item -ItemType Directory -Force $tclDir | Out-Null
foreach ($lib in @("tcl8", "tcl8.6", "tk8.6")) {
    Copy-Item (Join-Path $source "tcl\$lib") $tclDir -Recurse
}
$sitePackages = Join-Path $pythonDir "Lib\site-packages"
New-Item -ItemType Directory -Force $sitePackages | Out-Null
Copy-Item (Join-Path $source "Lib\tkinter") $sitePackages -Recurse
Say "  Tkinter added, signed by $($sig.SignerCertificate.Subject -replace '^CN=([^,]+).*','$1')" "DarkGray"

# --- 2. The app and everything it needs ------------------------------------
Say "  Installing the app and its libraries (a minute or two)..."
& $py -m pip install --quiet --disable-pip-version-check --target $sitePackages $root
if ($LASTEXITCODE -ne 0) { Say "  pip failed." "Red"; exit 1 }

# --- 3. The installer ------------------------------------------------------
$installer = Get-Content (Join-Path $here "Install.ps1") -Raw
$installer = $installer.Replace("__RELAY_URL__", $RelayUrl)
$installer = $installer.Replace("__GOOGLE_CLIENT_ID__", "$GoogleClientId")
$installer = $installer.Replace("__GOOGLE_CLIENT_SECRET__", "$GoogleClientSecret")
$installer | Out-File -FilePath (Join-Path $staging "Install.ps1") -Encoding utf8

# --- 4. The zip ------------------------------------------------------------
$zip = Join-Path $root "dist\MirabelVoice-$version-python.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Say "  Zipping..."
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zip
Remove-Item $staging -Recurse -Force

$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Say ""
Say "  Done. $zip ($size MB)" "Green"
Say ""
