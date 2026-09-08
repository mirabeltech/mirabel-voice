# Mirabel Voice: verify a company bundle, install it, or request an approved update.
param(
    [string]$DownloadsDir = '', [string]$WorkDir = '', [string]$Target = '',
    [string]$PythonExe = '', [string]$ManifestPath = '', [switch]$NoLaunch, [switch]$Repair
)
$ErrorActionPreference = 'Stop'
$driveLink = 'https://drive.google.com/drive/folders/0AL2zqxan1Ec6Uk9PVA'
$manifestUrl = 'https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/packaging/bundles.json'
if (-not $Target) { $Target = Join-Path $env:LOCALAPPDATA 'Programs\Mirabel Voice' }
if (-not $PythonExe) { $PythonExe = Join-Path $Target 'python\python.exe' }
if (-not $DownloadsDir) {
    try { $DownloadsDir = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders').'{374DE290-123F-4565-9164-39C4925E467B}' } catch {}
    if (-not $DownloadsDir) { $DownloadsDir = Join-Path $env:USERPROFILE 'Downloads' }
    $DownloadsDir = [Environment]::ExpandEnvironmentVariables($DownloadsDir)
}
function Find-Zip {
    @(Get-ChildItem -LiteralPath $DownloadsDir -File -ErrorAction SilentlyContinue) |
        Where-Object { $_.Name -match '^MirabelVoice-([0-9]+\.[0-9]+\.[0-9]+)-python(?: \(\d+\))?\.zip$' } |
        Sort-Object @{Expression={ [version]([regex]::Match($_.Name, '\d+\.\d+\.\d+').Value) }; Descending=$true}, LastWriteTime -Descending |
        Select-Object -First 1
}
function Request-Update {
    & $PythonExe -m mirabel_voice --request-update
    if ($LASTEXITCODE -ne 0) { throw 'This older copy needs the latest Python ZIP from the shared drive. Your working copy was left alone.' }
    $running = @(Get-Process python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($Target + '\', [StringComparison]::OrdinalIgnoreCase) })
    if (-not $NoLaunch -and -not $running.Count) {
        $launch = Join-Path $Target 'Launch.ps1'
        if (Test-Path $launch) { & $launch }
        else { Start-Process (Join-Path $Target 'python\pythonw.exe') -ArgumentList '-m','mirabel_voice' -WorkingDirectory $Target }
    }
}
$zip = Find-Zip
if ((Test-Path $PythonExe) -and -not $zip -and -not $Repair) { Request-Update; return }
if (-not $zip) {
    Write-Host "Download the Python ZIP from $driveLink, then run this command again."
    Start-Process $driveLink
    return
}
# The manifest is obtained separately from the ZIP. Never trust a checksum inside it.
if ($ManifestPath) { $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json }
else { $manifest = Invoke-RestMethod -Uri $manifestUrl -TimeoutSec 30 }
if ($manifest.schema -ne 1) { throw 'The release manifest is invalid. Nothing was installed.' }
$hash = (Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$release = @($manifest.bundles | Where-Object { $_.sha256 -eq $hash -and $_.version -match '^\d+\.\d+\.\d+$' -and $_.approved -eq $true })
if ($release.Count -ne 1) { throw 'This ZIP is not an approved download, or its download is incomplete. Get the approved Python ZIP from the shared drive. Nothing was changed.' }
if (Test-Path $PythonExe) {
    $versionFile = Join-Path $Target 'python\Lib\site-packages\mirabel_voice\_version.txt'
    if (Test-Path $versionFile) {
        $current = (Get-Content $versionFile -Raw).Trim()
        if ($current -eq $release[0].version -and -not $Repair) { Request-Update; return }
    }
}
# Work only in a newly created directory. Never erase a caller-supplied folder.
if (-not $WorkDir) { $WorkDir = $env:TEMP }
$work = Join-Path $WorkDir ('MirabelVoiceInstall-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Unblock-File -LiteralPath $zip.FullName
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zip.FullName)
    try {
        $total = 0L
        foreach ($entry in $archive.Entries) {
            $total += $entry.Length
            $entryPath = $entry.FullName.Replace('/', '\')
            if ([IO.Path]::IsPathRooted($entryPath) -or $entryPath.Contains(':')) { throw 'Unsafe ZIP path.' }
            foreach ($part in $entryPath.Split('\')) {
                if ($part -eq '.' -or $part -eq '..' -or ($part -and $part.TrimEnd(' ', '.') -ne $part)) { throw 'Unsafe ZIP path.' }
            }
        }
        if ($total -gt 1GB) { throw 'The expanded ZIP is too large.' }
        # Extended Windows paths require backslashes, including ZIP member names.
        # Validate every member above before writing any files.
        $destinationRoot = '\\?\' + [IO.Path]::GetFullPath($work).TrimEnd('\') + '\'
        foreach ($entry in $archive.Entries) {
            $entryPath = $entry.FullName.Replace('/', '\')
            $destination = $destinationRoot + $entryPath
            if ($entryPath.EndsWith('\')) {
                [IO.Directory]::CreateDirectory($destination) | Out-Null
            } else {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination)
            }
        }
    } finally { $archive.Dispose() }
    $installer = Join-Path $work 'Install.ps1'
    if (-not (Test-Path $installer)) { throw 'The approved ZIP has no installer.' }
    $installArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installer, '-Target', $Target)
    if ($NoLaunch) { $installArgs += '-NoLaunch' }
    & powershell @installArgs
    if ($LASTEXITCODE -ne 0) { throw 'Installation did not finish. Follow the message above; the previous copy was retained.' }
} finally { [IO.Directory]::Delete(('\\?\' + [IO.Path]::GetFullPath($work)), $true) }
