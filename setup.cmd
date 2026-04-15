@echo off
setlocal

set "REPO_ROOT=%~dp0"
set "SETUP_PS1=%REPO_ROOT%setup.ps1"

if not exist "%SETUP_PS1%" (
    echo ERROR: setup.ps1 was not found at:
    echo   %SETUP_PS1%
    exit /b 1
)

where powershell.exe >nul 2>nul
if errorlevel 1 (
    echo ERROR: powershell.exe was not found on PATH.
    echo Install Windows PowerShell 5.1 and run setup.cmd again.
    exit /b 1
)

echo.
echo === QgisPortAgent setup.cmd ===
echo Launching setup.ps1 from Command Prompt...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_PS1%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo setup.ps1 exited with code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
