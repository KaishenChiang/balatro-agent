@echo off
setlocal DisableDelayedExpansion
title Balatro Agent Setup
echo Balatro Agent first-time setup for Windows x64 and Steam.
echo Close Balatro normally before continuing. Internet is needed for missing dependencies.
echo This installs project-local Python, required Mods and the Codex MCP configuration.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" -Install
set "BALATRO_SETUP_EXIT=%ERRORLEVEL%"
echo.
if "%BALATRO_SETUP_EXIT%"=="0" (
    echo Setup completed. Open or reload Codex, then follow README.md.
) else (
    echo Setup stopped. Keep the output and any receipts; follow README.md for recovery.
)
echo.
pause
exit /b %BALATRO_SETUP_EXIT%
