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
