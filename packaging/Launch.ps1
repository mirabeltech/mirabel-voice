# Stable current-user entry point. Never downloads or changes Windows security.
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
try {
    $lock = [IO.File]::Open((Join-Path $root '.update.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    try {
        $runtime = Join-Path $root 'python'
        $backup = Join-Path $root 'python.previous'
        $journal = Join-Path $root '.install-pending'
        if ((Test-Path $journal) -and (Test-Path $backup)) {
            if (Test-Path $runtime) { [IO.Directory]::Delete(('\\?\' + $runtime), $true) }
            Move-Item $backup $runtime
            Remove-Item $journal -Force
        } elseif ((Test-Path $journal) -and (Test-Path $runtime)) {
            & (Join-Path $runtime 'python.exe') -m mirabel_voice --self-test | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Interrupted first install needs repair.' }
            Remove-Item $journal -Force
        } elseif (-not (Test-Path $runtime) -and (Test-Path $backup)) {
            Move-Item $backup $runtime
        }
    } finally { $lock.Dispose() }
    if ($CheckOnly) {
        & (Join-Path $runtime 'python.exe') (Join-Path $root 'launcher.py') --self-test
        if ($LASTEXITCODE -ne 0) { throw 'Recovered app failed offline checks.' }
        return
    }
    Start-Process -FilePath (Join-Path $runtime 'pythonw.exe') -ArgumentList ('"' + (Join-Path $root 'launcher.py') + '"') -WorkingDirectory $root
} catch {
    if ($CheckOnly) { throw }
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show('Mirabel Voice could not start. If an update is running, wait and try again. Otherwise, run the bundle installer to repair it.', 'Mirabel Voice') | Out-Null
}
