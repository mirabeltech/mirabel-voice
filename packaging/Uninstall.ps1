param([switch]$RemoveSettings, [switch]$SkipIntegration)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not (Test-Path (Join-Path $root '.installed'))) { throw 'Use Mirabel Voice in Windows Installed apps to remove the installed copy.' }
$running = @(Get-Process python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) })
if ($running.Count) { throw 'Choose Quit from the microphone icon before uninstalling.' }
$lock = [IO.File]::Open((Join-Path $root '.update.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    if (-not $SkipIntegration) {
    foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Startup'))) {
        Remove-Item (Join-Path $folder 'Mirabel Voice.lnk') -Force -ErrorAction SilentlyContinue
    }
    Remove-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' 'Mirabel Voice' -ErrorAction SilentlyContinue
    Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MirabelVoice' -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($name in @('python','python.previous','python.new','__pycache__')) {
        $path = Join-Path $root $name
        if (Test-Path $path) { [IO.Directory]::Delete(('\\?\' + $path), $true) }
    }
    if ($RemoveSettings) {
        $settings = if ($env:MIRABEL_VOICE_HOME) { $env:MIRABEL_VOICE_HOME } else { Join-Path $env:APPDATA 'MirabelVoice' }
        if (Test-Path $settings) { [IO.Directory]::Delete(('\\?\' + $settings), $true) }
    }
} finally { $lock.Dispose() }
foreach ($name in @('Launch.ps1','launcher.py','recovery.py','Uninstall.ps1','.installed','.install-pending','.update.lock','.update-request')) {
    $file = Join-Path $root $name
    if (Test-Path -LiteralPath $file -PathType Leaf) { [IO.File]::Delete($file) }
}
if ([IO.Directory]::GetFileSystemEntries($root).Count -eq 0) { [IO.Directory]::Delete($root) }
else { Write-Host 'Additional files in the installation folder were kept.' }
Write-Host 'Mirabel Voice removed. Settings are kept unless -RemoveSettings was selected.'
