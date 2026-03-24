# Analisi_Spettrale_CC Installation Script for Windows
# This script checks for Python, installs dependencies, and creates a launcher.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Analisi_Spettrale_CC Setup (Windows) " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

function Get-PythonInvocation {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3") }
        @{ Exe = "python"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        try {
            $null = & $candidate.Exe @($candidate.Args + "--version") 2>$null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            # try next candidate
        }
    }

    return $null
}

function Invoke-SelectedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    & $script:PythonExe @script:PythonBaseArgs @Args
}

Write-Host "Checking for Python installation..." -ForegroundColor Yellow
$pythonInvocation = Get-PythonInvocation

if ($null -eq $pythonInvocation) {
    Write-Host "[ERROR] Python 3.7+ is not installed (or not available as 'py -3' / 'python')." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/downloads/windows/" -ForegroundColor Yellow
    Write-Host "During installation, enable 'Add python.exe to PATH'." -ForegroundColor Yellow
    exit 1
}

$script:PythonExe = $pythonInvocation.Exe
$script:PythonBaseArgs = $pythonInvocation.Args

$versionText = Invoke-SelectedPython -Args @("--version") 2>&1
$versionNumber = Invoke-SelectedPython -Args @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
$version = [version]$versionNumber

Write-Host "[OK] Python found: $versionText" -ForegroundColor Green

if ($version -lt [version]"3.7") {
    Write-Host "[ERROR] Python version is too old. Python 3.7 or higher is required." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Creating virtual environment..." -ForegroundColor Yellow

if (-not (Test-Path ".venv")) {
    Invoke-SelectedPython -Args @("-m", "venv", ".venv")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "[OK] Virtual environment already exists." -ForegroundColor Cyan
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Virtual environment Python executable not found: $venvPython" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Installing dependencies..." -ForegroundColor Yellow
Write-Host "This may take a few minutes..." -ForegroundColor Cyan

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to upgrade pip." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "requirements.txt")) {
    Write-Host "[ERROR] requirements.txt not found in project root." -ForegroundColor Red
    exit 1
}

& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to install dependencies from requirements.txt." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] All dependencies installed." -ForegroundColor Green

Write-Host ""
Write-Host "Creating launcher (Analizzatore.bat)..." -ForegroundColor Yellow

$launcherContent = @'
@echo off
title Analisi_Spettrale_CC

set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"

if not exist "%VENV_PYW%" (
    echo Error: virtual environment not found.
    echo Run install.ps1 first.
    pause
    exit /b 1
)

start "" "%VENV_PYW%" "%~dp0main.py"
'@

if (Test-Path "launch.bat") {
    Remove-Item "launch.bat" -Force
}

Set-Content -Path "Analizzatore.bat" -Value $launcherContent -Encoding ASCII

if (-not (Test-Path "Analizzatore.bat")) {
    Write-Host "[ERROR] Failed to create Analizzatore.bat" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Launcher created: Analizzatore.bat" -ForegroundColor Green

if (-not (Test-Path "results")) {
    New-Item -ItemType Directory -Path "results" -Force | Out-Null
    Write-Host "[OK] Created output directory: results" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installation Complete!                " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Run the app with:" -ForegroundColor Yellow
Write-Host "  .\Analizzatore.bat" -ForegroundColor White
Write-Host ""
Write-Host "Or manually with:" -ForegroundColor Yellow
Write-Host "  .\.venv\Scripts\pythonw.exe .\main.py" -ForegroundColor White
Write-Host ""
