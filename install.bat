@echo off
REM Analisi_Spettrale_CC Installation Script for Windows
REM Non-interactive batch installer (no execution policy issues)

setlocal enabledelayedexpansion

echo ========================================
echo Analisi_Spettrale_CC Setup (Windows)
echo ========================================
echo.

REM Check if Python is in PATH
for /f "tokens=*" %%i in ('py -3 --version 2^>nul') do (
    set PYTHON_CMD=py -3
    set PYTHON_VERSION=%%i
    goto :python_found
)

for /f "tokens=*" %%i in ('python --version 2^>nul') do (
    set PYTHON_CMD=python
    set PYTHON_VERSION=%%i
    goto :python_found
)

echo [WARNING] Python 3.7+ not found in PATH
echo.
set /p AUTO_INSTALL="Auto-install Python? (Y/N): "
if /i "!AUTO_INSTALL!"=="N" (
    echo.
    echo Please install Python from: https://www.python.org/downloads/windows/
    echo During installation, check "Add python.exe to PATH"
    echo.
    pause
    exit /b 1
)

REM Try winget first (Windows 11 / recent Windows 10)
winget install --id Python.Python.3.12 --quiet --accept-source-agreements 2>nul
if !errorlevel! EQU 0 (
    echo [OK] Python installed via winget
    echo.
    echo Restarting installer...
    echo.
    call "%~f0"
    exit /b 0
)

REM Fallback: download and install using PowerShell
echo [INFO] Downloading Python installer...
powershell -NoProfile -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
    "$url = 'https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe'; " ^
    "$outFile = Join-Path $PWD 'python-installer.exe'; " ^
    "try { Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing } " ^
    "catch { Write-Host '[ERROR] Failed to download Python'; exit 1 }" 2>nul

if not exist "python-installer.exe" (
    echo [ERROR] Failed to download Python installer
    echo.
    echo Please download manually from: https://www.python.org/downloads/windows/
    echo.
    pause
    exit /b 1
)

echo [INFO] Installing Python (this may take 2-3 minutes)...
python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_doc=0 Include_tcltk=0
if !errorlevel! NEQ 0 (
    echo [ERROR] Python installation failed
    del /q "python-installer.exe"
    pause
    exit /b 1
)

del /q "python-installer.exe"
echo [OK] Python installed successfully
echo.
echo Restarting installer...
call "%~f0"
exit /b 0

:python_found
echo [OK] Python found: !PYTHON_VERSION!
echo.

REM Check Python version (3.7 or higher)
for /f "tokens=2" %%i in ('!PYTHON_CMD! --version 2^>^&1') do (
    for /f "tokens=1,2 delims=." %%a in ("%%i") do (
        if %%a LSS 3 (
            echo [ERROR] Python version is too old. Need 3.7 or higher.
            pause
            exit /b 1
        )
        if %%a EQU 3 if %%b LSS 7 (
            echo [ERROR] Python version is too old. Need 3.7 or higher.
            pause
            exit /b 1
        )
    )
)

echo.
echo Creating virtual environment...

if exist ".venv" (
    echo [OK] Virtual environment already exists
) else (
    !PYTHON_CMD! -m venv .venv
    if !errorlevel! NEQ 0 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

echo.
echo Installing dependencies...
echo This may take a few minutes...
echo.

set VENV_PY=.venv\Scripts\python.exe

if not exist "!VENV_PY!" (
    echo [ERROR] Virtual environment Python executable not found
    pause
    exit /b 1
)

!VENV_PY! -m pip install --upgrade pip
if !errorlevel! NEQ 0 (
    echo [ERROR] Failed to upgrade pip
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found in project root
    pause
    exit /b 1
)

!VENV_PY! -m pip install -r requirements.txt
if !errorlevel! NEQ 0 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

echo [OK] All dependencies installed
echo.

echo Creating launcher (Analizzatore.bat)...

REM Delete old launcher if exists
if exist "Analizzatore.bat" del /q "Analizzatore.bat"

(
    echo @echo off
    echo title Analisi_Spettrale_CC
    echo.
    echo set "VENV_PYW=%%~dp0.venv\Scripts\pythonw.exe"
    echo.
    echo if not exist "%%VENV_PYW%%" ^(
    echo     echo Error: virtual environment not found.
    echo     echo Run install.bat first.
    echo     pause
    echo     exit /b 1
    echo ^)
    echo.
    echo start "" "%%VENV_PYW%%" "%%~dp0main.py"
) > Analizzatore.bat

if exist "Analizzatore.bat" (
    echo [OK] Launcher created: Analizzatore.bat
) else (
    echo [ERROR] Failed to create Analizzatore.bat
    pause
    exit /b 1
)

if not exist "results" (
    mkdir results
    echo [OK] Created output directory: results
)

echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo Run the app with:
echo   Analizzatore.bat
echo.
echo Or manually with:
echo   .venv\Scripts\pythonw.exe .\main.py
echo.
pause
