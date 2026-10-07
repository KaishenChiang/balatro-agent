@echo off
setlocal DisableDelayedExpansion
if exist "%~dp0Balatro Agent.exe" (
    start "" "%~dp0Balatro Agent.exe"
    exit /b 0
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\launcher.ps1"
exit /b %ERRORLEVEL%
