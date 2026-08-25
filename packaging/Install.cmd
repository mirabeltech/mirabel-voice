@echo off
rem Mirabel Voice - double-click me to install.
rem
rem This only hands the real work to Install.ps1 in this folder. It
rem exists because Windows 11 hides "Run with PowerShell" behind a
rem second menu, and a double-click needs no menu at all.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"
echo.
pause
