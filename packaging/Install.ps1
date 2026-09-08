# Run only from the approved company Python ZIP. No administrator privileges needed.
param([string]$Token = '', [string]$Target = '', [switch]$NoLaunch, [switch]$SkipShortcuts)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
if ($architecture -ne 'AMD64') { throw 'This download supports Windows x64. Ask Tommy about a compatible download for this computer; nothing was installed.' }
$relayUrl = '__RELAY_URL__'
$googleClientId = '__GOOGLE_CLIENT_ID__'
$googleClientSecret = '__GOOGLE_CLIENT_SECRET__'
if (-not $Target) { $Target = Join-Path $env:LOCALAPPDATA 'Programs\Mirabel Voice' }
$target = [IO.Path]::GetFullPath($Target)
$source = Join-Path $here 'python'
if ((Test-Path $target) -and -not (Test-Path (Join-Path $target '.installed')) -and -not (Test-Path (Join-Path $target 'python\Lib\site-packages\mirabel_voice\__init__.py'))) {
    $unexpected = @(Get-ChildItem -LiteralPath $target -Force | Where-Object { $_.Name -notin @('.update.lock','.install-pending','python.new','python.previous','Launch.ps1','launcher.py','recovery.py','Uninstall.ps1','Launch.ps1.new','launcher.py.new','recovery.py.new','Uninstall.ps1.new','__pycache__') })
    if ($unexpected.Count) { throw 'Choose an empty folder or an existing Mirabel Voice installation. This folder contains other files.' }
}
if (-not (Test-Path (Join-Path $source 'python.exe'))) { throw 'Get the Python ZIP, extract the whole download, and run Install.ps1 from that folder.' }
if ($source.TrimEnd('\') -eq (Join-Path $target 'python')) { throw 'Run the installer from the extracted download, not the installed app.' }
if ($relayUrl -notmatch '^https://' -or $relayUrl -like '*__RELAY*') { throw 'This bundle has no valid relay configuration.' }
# Refuse rather than forcibly terminating an active recording or unrelated Python.
$running = @(Get-Process python,pythonw,MirabelVoice -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase) })
if ($running.Count) { throw 'Finish dictating, choose Quit from the microphone icon, then run this installer again. Your current copy was left alone.' }
New-Item -ItemType Directory -Force $target | Out-Null
$lock = $null
try { $lock = [IO.File]::Open((Join-Path $target '.update.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
catch { throw 'Another installation or update is running. Wait and try again.' }
$runtime = Join-Path $target 'python'
$incoming = Join-Path $target 'python.new'
$backup = Join-Path $target 'python.previous'
$journal = Join-Path $target '.install-pending'
try {
    if ((Test-Path $journal) -and (Test-Path $backup)) {
        if (Test-Path $runtime) { [IO.Directory]::Delete(('\\?\' + $runtime), $true) }
        Move-Item $backup $runtime
        Remove-Item $journal
    } elseif (-not (Test-Path $runtime) -and (Test-Path $backup)) { Move-Item $backup $runtime }
    if (Test-Path $incoming) { [IO.Directory]::Delete(('\\?\' + $incoming), $true) }
    Write-Host 'Checking the new app before changing your installation...'
    & robocopy.exe $source $incoming /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw 'Could not copy the new bundle. Check disk space and folder permissions. The current copy was retained.' }
    $console = Join-Path $incoming 'python.exe'
    & $console -m mirabel_voice --self-test
    if ($LASTEXITCODE -ne 0) { throw 'The new bundle failed its checks. The working version was retained.' }
    $googleMode = $googleClientId -and $googleClientSecret -and $googleClientId -notlike '__GOOGLE*'
    # Configure through the staged app. Atomic settings writes retain preferences.
    & $console -m mirabel_voice --set-relay $relayUrl | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not save relay settings. Repair config.json and retry.' }
    if ($googleMode) {
        & $console -m mirabel_voice --set-google $googleClientId $googleClientSecret | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not save sign-in settings.' }
    } else {
        & $console -m mirabel_voice --has-relay-token | Out-Null
        if ($LASTEXITCODE -ne 0 -and -not $Token) { $Token = Read-Host 'Your Mirabel token (ask the support contact)' }
        if ($Token) {
            & $console -m mirabel_voice --set-relay $relayUrl $Token | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not save the token.' }
        }
        & $console -m mirabel_voice --check-keys
        if ($LASTEXITCODE -ne 0) { throw 'Sign-in could not be checked. Verify the connection/token and retry. Existing credentials were not cleared.' }
    }
    # Stable launch/recovery lives outside the runtime directory being replaced.
    foreach ($name in @('Launch.ps1','launcher.py','recovery.py','Uninstall.ps1')) {
        Copy-Item (Join-Path $here $name) (Join-Path $target ($name + '.new')) -Force
        Move-Item (Join-Path $target ($name + '.new')) (Join-Path $target $name) -Force
    }
    if (Test-Path $backup) { [IO.Directory]::Delete(('\\?\' + $backup), $true) }
    $hadRuntime = Test-Path $runtime
    [IO.File]::WriteAllText($journal, 'pending')
    try {
        if (Test-Path $runtime) { Move-Item $runtime $backup }
        Move-Item $incoming $runtime
        & (Join-Path $runtime 'python.exe') -m mirabel_voice --self-test
        if ($LASTEXITCODE -ne 0) { throw 'The installed bundle failed its checks.' }
        Remove-Item $journal
    } catch {
        if (Test-Path $backup) {
            if (Test-Path $runtime) { [IO.Directory]::Delete(('\\?\' + $runtime), $true) }
            Move-Item $backup $runtime
        } elseif (-not $hadRuntime -and (Test-Path $runtime)) { [IO.Directory]::Delete(('\\?\' + $runtime), $true) }
        Remove-Item $journal -Force -ErrorAction SilentlyContinue
        throw
    }
    [IO.File]::WriteAllText((Join-Path $target '.installed'), 'Mirabel Voice')
    if (-not $SkipShortcuts) {
        $shell = New-Object -ComObject WScript.Shell
        foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
            $link = $shell.CreateShortcut((Join-Path $folder 'Mirabel Voice.lnk'))
            $link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
            $link.Arguments = '-NoProfile -WindowStyle Hidden -File "' + (Join-Path $target 'Launch.ps1') + '"'
            $link.WorkingDirectory = $target
            $link.IconLocation = (Join-Path $runtime 'MirabelVoice.ico') + ',0'
            $link.Save()
        }
        $console = Join-Path $runtime 'python.exe'
        $settingsPath = (& $console -m mirabel_voice --config).Trim()
        $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        $startup = if ($settings.start_with_windows -eq $false) { 'off' } else { 'on' }
        & $console -m mirabel_voice --set-startup $startup
        if ($LASTEXITCODE -ne 0) { throw 'The app was installed but Windows startup could not be configured.' }
        $reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MirabelVoice'
        New-Item $reg -Force | Out-Null
        $version = (Get-Content (Join-Path $runtime 'Lib\site-packages\mirabel_voice\_version.txt') -Raw).Trim()
        New-ItemProperty $reg DisplayName -Value 'Mirabel Voice' -Force | Out-Null
        New-ItemProperty $reg DisplayVersion -Value $version -Force | Out-Null
        New-ItemProperty $reg UninstallString -Value ('powershell.exe -NoProfile -File "' + (Join-Path $target 'Uninstall.ps1') + '"') -Force | Out-Null
    }
    Write-Host 'Installed. Start Mirabel Voice from the Start menu. Your settings have been kept.'
} finally {
    if ($lock) { $lock.Dispose() }
    if (Test-Path $incoming) { [IO.Directory]::Delete(('\\?\' + $incoming), $true) }
}
if (-not $NoLaunch) { & (Join-Path $target 'Launch.ps1') }
