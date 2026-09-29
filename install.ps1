# Healthcare HR Job Aggregator - Windows 11 Installation Script

param(
    [switch]$CleanInstall
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$AppUrl = "http://127.0.0.1:8000"
Write-Host "--- Healthcare HR Job Aggregator Installation ---" -ForegroundColor Cyan
if ($CleanInstall) {
    Write-Host "Clean install requested. Existing database will be removed if present." -ForegroundColor Yellow
}

function Stop-RunningApp {
    $pythonPaths = @(
        [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".venv\Scripts\python.exe")),
        [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"))
    )
    $scriptPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "run_app.py"))
    $scriptPattern = '(?i)(?:^|\s|")' + [regex]::Escape($scriptPath) + '(?:\s|"|$)'
    $appProcesses = Get-CimInstance Win32_Process |
        Where-Object {
            $_.ExecutablePath -and
            $_.CommandLine -and
            $pythonPaths -contains ([System.IO.Path]::GetFullPath($_.ExecutablePath)) -and
            $_.CommandLine -match $scriptPattern
        }

    foreach ($process in $appProcesses) {
        Write-Host "Stopping running Healthcare HR Job Aggregator process (PID $($process.ProcessId))..." -ForegroundColor Yellow
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    if ($appProcesses) {
        Start-Sleep -Seconds 2
    }
}

function Remove-FileWithRetry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [int]$Attempts = 5
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Remove-Item $Path -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq $Attempts) {
                throw
            }
            Write-Host "File is still locked, retrying ($attempt/$Attempts)..." -ForegroundColor Yellow
            Start-Sleep -Seconds 1
        }
    }
}

function Start-InstalledApp {
    $pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $pythonPath)) {
        $pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    }

    if (-not (Test-Path $pythonPath)) {
        throw "Cannot start the app because no Python executable was found in .venv\Scripts."
    }

    Write-Host "Starting Healthcare HR Job Aggregator..." -ForegroundColor Cyan
    Stop-RunningApp
    Start-Process -FilePath $pythonPath -ArgumentList "`"$PSScriptRoot\run_app.py`"" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden

    for ($attempt = 1; $attempt -le 40; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-WebRequest -Uri "$AppUrl/api/offer-filter-options" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                Write-Host "Application is ready. Opening dashboard..." -ForegroundColor Green
                Start-Process $AppUrl
                return $true
            }
        } catch {
        }
    }

    Write-Host "The app process was started, but the dashboard did not respond at $AppUrl yet." -ForegroundColor Yellow
    Write-Host "Use the desktop shortcut or check logs\\app.log if the page still does not open." -ForegroundColor Yellow
    return $false
}

# 1. Check for Python
try {
    $pythonVer = python --version 2>&1
    Write-Host "Detected $pythonVer" -ForegroundColor Green
} catch {
    Write-Host "Error: Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from https://www.python.org/downloads/"
    exit
}

# 2. Clean existing database if requested
if ($CleanInstall -and (Test-Path ".\data\apjobs.db")) {
    Stop-RunningApp
    Write-Host "Removing existing database file..." -ForegroundColor Yellow
    Remove-FileWithRetry -Path ".\data\apjobs.db"
}

# 3. Create Virtual Environment
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
} else {
    Write-Host "Virtual environment already exists." -ForegroundColor Yellow
}

# 4. Install Dependencies
Write-Host "Upgrading pip and installing dependencies..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed with exit code $LASTEXITCODE. Check the network connection and installation output above."
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed with exit code $LASTEXITCODE. Check requirements.txt and the installation output above."
}

# 4. Initialize Environment File
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env file from .env.example..." -ForegroundColor Cyan
    Copy-Item .env.example .env
}

# 5. Create Desktop Shortcut
Write-Host "Creating Desktop shortcut..." -ForegroundColor Cyan
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\Healthcare HR Job Aggregator.lnk")
$LauncherPath = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $LauncherPath)) {
    $LauncherPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
}
$Shortcut.TargetPath = $LauncherPath
$Shortcut.Arguments = "`"$PSScriptRoot\run_app.py`""
$Shortcut.WorkingDirectory = "$PSScriptRoot"
$Shortcut.Description = "Launch Healthcare HR Job Aggregator Dashboard"
$IconPath = Join-Path $PSScriptRoot "app\static\favicon.ico"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath,0"
}
$Shortcut.Save()

$appStarted = Start-InstalledApp
if (-not $appStarted) {
    Write-Host "`nDependencies were installed and the desktop shortcut was created, but the application did not start." -ForegroundColor Red
    Write-Host "Check $PSScriptRoot\logs\app.log for the startup error, then try the desktop shortcut again." -ForegroundColor Yellow
    exit 1
}

Write-Host "`nInstallation Successful!" -ForegroundColor Green
Write-Host "The application is running. You can start it later using the desktop shortcut." -ForegroundColor White
