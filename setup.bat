@echo off
setlocal
cd /d "%~dp0"
echo Healthcare HR Job Aggregator installer for Windows 11
echo.
echo This file can be started by double-clicking it.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
    echo Installation ended with an error. Review the messages above and press any key to close this window.
    pause >nul
    exit /b %EXIT_CODE%
)
echo Installation finished. Press any key to close this window.
pause >nul
exit /b 0
