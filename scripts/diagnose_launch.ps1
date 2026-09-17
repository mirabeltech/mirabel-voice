# Mirabel Voice launch report.
# Run this on a computer where Mirabel Voice does not seem to start:
#   powershell -ExecutionPolicy Bypass -File diagnose_launch.ps1
# It writes mirabel-launch-report.txt to the Desktop and opens it. Send
# that file. It contains no dictation text, credentials or account names.
# Add -NoLaunch to skip the final start attempt.
param([switch]$NoLaunch)
$ErrorActionPreference = 'Continue'
$report = Join-Path ([Environment]::GetFolderPath('Desktop')) 'mirabel-launch-report.txt'
$lines = New-Object System.Collections.Generic.List[string]
function Say($text) { $script:lines.Add([string]$text); Write-Host $text }
function Section($title) { Say ''; Say "== $title" }

$root = Join-Path $env:LOCALAPPDATA 'Programs\Mirabel Voice'
$runtime = Join-Path $root 'python'
$py = Join-Path $runtime 'python.exe'
$logs = Join-Path $env:APPDATA 'MirabelVoice\logs'

Say "Mirabel Voice launch report  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Say "Windows $([Environment]::OSVersion.Version)  user profile: $env:USERNAME"

Section 'Install folder'
Say "$root  exists=$(Test-Path $root)"
foreach ($name in '.installed', '.install-pending', '.update.lock', 'python', 'python.new', 'python.previous', 'Launch.ps1', 'launcher.py', 'recovery.py', 'python\python.exe', 'python\pythonw.exe', 'python\Lib\site-packages\mirabel_voice\__init__.py') {
    $path = Join-Path $root $name
    $stamp = if (Test-Path $path) { (Get-Item $path).LastWriteTime.ToString('yyyy-MM-dd HH:mm') } else { 'MISSING' }
    Say ("  {0,-55} {1}" -f $name, $stamp)
}
$markers = Get-ChildItem (Join-Path $runtime 'Lib\site-packages') -Filter 'mirabel_voice-*.dist-info' -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }
Say "  installed package: $($markers -join ', ')"

Section 'Running copies'
$procs = @(Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) })
if ($procs.Count -eq 0) { Say '  none from the install folder' }
foreach ($p in $procs) { Say ("  pid {0}  {1}  started {2}  responding={3}" -f $p.Id, $p.ProcessName, $p.StartTime.ToString('yyyy-MM-dd HH:mm:ss'), $p.Responding) }
$others = @(Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object { -not ($_.Path -and $_.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) })
if ($others.Count) { Say "  other python processes (not from the install): $($others.Count)" }

Section 'Single-instance mutex'
$mutexScript = Join-Path $env:TEMP 'mirabel-mutex-check.py'
@'
import ctypes
k = ctypes.windll.kernel32
k.CreateMutexW.restype = ctypes.c_void_p
k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
k.CreateMutexW(None, False, "Local\\MirabelVoiceSingleInstance")
print("HELD (a copy is running, or a dead copy still holds it)" if k.GetLastError() == 183 else "free (nothing is running)")
'@ | Set-Content $mutexScript -Encoding ASCII
function MutexState { if (Test-Path $py) { & $py $mutexScript 2>&1 } else { 'unknown' } }
$mutex = MutexState
Say "  $mutex"

Section 'How Windows starts it'
$shell = New-Object -ComObject WScript.Shell
foreach ($place in @(
        @{ name = 'Start menu'; path = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mirabel Voice.lnk' },
        @{ name = 'Desktop'; path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mirabel Voice.lnk' },
        @{ name = 'Taskbar pin'; path = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Mirabel Voice.lnk' })) {
    if (Test-Path $place.path) {
        $link = $shell.CreateShortcut($place.path)
        Say "  $($place.name): $($link.TargetPath) $($link.Arguments)"
        Say "      working dir: $($link.WorkingDirectory)"
        $script = ($link.Arguments -replace '.*-File\s+"([^"]+)".*', '$1')
        if ($script -and $script -ne $link.Arguments) { Say "      launch script exists: $(Test-Path $script)" }
    } else { Say "  $($place.name): no shortcut" }
}
$run = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Mirabel Voice' -ErrorAction SilentlyContinue
Say "  Start with Windows: $(if ($run) { $run.'Mirabel Voice' } else { 'not set' })"
$policy = Get-ExecutionPolicy -List | ForEach-Object { "$($_.Scope)=$($_.ExecutionPolicy)" }
Say "  PowerShell execution policy: $($policy -join ' ')"

Section 'Offline self-test (the same check the launcher runs)'
if (Test-Path $py) {
    $out = & $py (Join-Path $root 'launcher.py') --self-test 2>&1
    Say "  exit code $LASTEXITCODE"
    foreach ($line in $out) { Say "  $line" }
} else { Say '  python.exe is missing, so the app cannot start at all' }

Section 'Log tail'
foreach ($name in 'mirabel-voice.log', 'shutdown-timeout.log') {
    $path = Join-Path $logs $name
    if (Test-Path $path) {
        Say "  --- $name (last 40 lines, modified $((Get-Item $path).LastWriteTime.ToString('yyyy-MM-dd HH:mm')))"
        Get-Content $path -Tail 40 | ForEach-Object { Say "  $_" }
    } else { Say "  $name : not present" }
}

if (-not $NoLaunch -and (Test-Path $py) -and $mutex -like 'free*') {
    Section 'Start attempt with errors visible (15 seconds)'
    $err = Join-Path $env:TEMP 'mirabel-launch-stderr.txt'
    $proc = Start-Process -FilePath $py -ArgumentList ('"' + (Join-Path $root 'launcher.py') + '" --verbose') -WorkingDirectory $root -RedirectStandardError $err -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 15
    $alive = -not $proc.HasExited
    Say "  still running after 15 s: $alive  (exit code: $(if ($alive) { 'n/a' } else { $proc.ExitCode }))"
    Say "  mutex now: $(MutexState)"
    if (Test-Path $err) { Get-Content $err -Tail 40 | ForEach-Object { Say "  stderr: $_" } }
    if ($alive) { Say '  The app started from python.exe. Look for the microphone icon near the clock now.' }
} elseif (-not $NoLaunch) {
    Section 'Start attempt skipped'
    Say "  Reason: $(if (-not (Test-Path $py)) { 'python.exe missing' } else { 'the mutex is held' })"
}

[IO.File]::WriteAllLines($report, $lines)
Say ''
Say "Report written to $report"
Start-Process notepad.exe $report
