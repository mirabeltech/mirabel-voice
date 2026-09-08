# Offline acceptance of the produced Google-sign-in ZIP; no user app/registry changes.
param([Parameter(Mandatory=$true)][string]$Bundle)
$ErrorActionPreference = 'Stop'
$base = Join-Path $env:TEMP ('MirabelBundleCheck-' + [guid]::NewGuid().ToString('N'))
$previousHome = $env:MIRABEL_VOICE_HOME
$unpacked = Join-Path $base 'download'
$target = Join-Path $base 'installed app'
try {
    New-Item -ItemType Directory $base | Out-Null
    $env:MIRABEL_VOICE_HOME = Join-Path $base 'isolated-settings'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path $Bundle))
    try {
        foreach ($entry in $archive.Entries) {
            $entryPath = $entry.FullName.Replace('/', '\')
            if ([IO.Path]::IsPathRooted($entryPath) -or $entryPath.Contains(':')) { throw 'Unsafe ZIP path.' }
            foreach ($part in $entryPath.Split('\')) {
                if ($part -eq '.' -or $part -eq '..' -or ($part -and $part.TrimEnd(' ', '.') -ne $part)) { throw 'Unsafe ZIP path.' }
            }
        }
        foreach ($entry in $archive.Entries) {
            $entryPath = $entry.FullName.Replace('/', '\')
            $destination = '\\?\' + $unpacked + '\' + $entryPath
            if ($entryPath.EndsWith('\')) {
                [IO.Directory]::CreateDirectory($destination) | Out-Null
            } else {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination)
            }
        }
    } finally { $archive.Dispose() }
    & (Join-Path $unpacked 'Install.ps1') -Target $target -NoLaunch -SkipShortcuts
    if ($LASTEXITCODE -ne 0) { throw 'Isolated installation failed' }
    $py = Join-Path $target 'python\python.exe'
    & $py -c "from mirabel_voice.config import Config;c=Config.load();c.hotkey='f13';c.custom_words=['Synthetic retained preference'];c.save()"
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare test settings' }
    & (Join-Path $unpacked 'Install.ps1') -Target $target -NoLaunch -SkipShortcuts
    if ($LASTEXITCODE -ne 0) { throw 'Isolated repair failed' }
    & $py -c "from mirabel_voice.config import Config;c=Config.load();assert c.hotkey=='f13';assert c.custom_words==['Synthetic retained preference'];print('Settings survived repair')"
    if ($LASTEXITCODE -ne 0) { throw 'Settings were lost during repair' }
    # Simulate a power loss between runtime renames inside this disposable copy.
    [IO.Directory]::Delete(('\\?\' + (Join-Path $target 'python.previous')), $true)
    Move-Item (Join-Path $target 'python') (Join-Path $target 'python.previous')
    Set-Content (Join-Path $target '.install-pending') 'pending'
    & (Join-Path $target 'Launch.ps1') -CheckOnly
    if (-not (Test-Path $py)) { throw 'Runtime recovery failed' }
    # Simulate a source-package switch interrupted before startup proof.
    $package = Join-Path $target 'python\Lib\site-packages\mirabel_voice'
    Move-Item $package ($package + '.previous')
    Set-Content ($package + '.transaction.json') '{"state":"pending"}' -Encoding ascii
    & (Join-Path $target 'Launch.ps1') -CheckOnly
    if (-not (Test-Path $package)) { throw 'Source recovery failed' }
    & (Join-Path $target 'Uninstall.ps1') -SkipIntegration
    if ((Test-Path $target) -or -not (Test-Path $env:MIRABEL_VOICE_HOME)) { throw 'Removal or settings retention failed' }
    Write-Host 'PASS: produced ZIP installation, repair, settings retention, runtime and source recovery. No microphone/network/registration used.'
} finally {
    $env:MIRABEL_VOICE_HOME = $previousHome
    if (Test-Path $base) { [IO.Directory]::Delete(('\\?\' + $base), $true) }
}
