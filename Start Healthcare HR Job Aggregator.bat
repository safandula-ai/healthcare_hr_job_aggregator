@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW_PATH=%~dp0.venv\Scripts\pythonw.exe"
set "PYTHON_PATH=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_PATH%" (
    echo Python environment not found in .venv\Scripts\python.exe
    echo Run Install Healthcare HR Job Aggregator.bat first.
    pause
    exit /b 1
)

if exist "%PYTHONW_PATH%" (
    start "" "%PYTHONW_PATH%" "%~dp0run_app.py"
) else (
    start "" "%PYTHON_PATH%" "%~dp0run_app.py"
)

exit /b 0
