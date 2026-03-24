# Analisi_Spettrale_CC Installation Guide

This guide describes how to install and run the project, especially on Windows.

## Windows Installation (Recommended)

### Method 1: Batch Script (No execution policy issues)

1. Double-click `install.bat` in the project folder
   
   **OR** open Command Prompt and run:
   ```batch
   install.bat
   ```

2. The installer will:
   - detect Python 3.7+ (`py -3` or `python`)
   - create `.venv`
   - install all packages from `requirements.txt`
   - create `Analizzatore.bat`
   - ensure the `results` folder exists

3. Start the app with:
   ```batch
   Analizzatore.bat
   ```

`Analizzatore.bat` uses `.venv\Scripts\pythonw.exe` to launch `main.py` without a terminal window.

### Method 2: PowerShell Script (Alternative)

1. Open PowerShell in the project folder and run:
   ```powershell
   .\install.ps1
   ```

2. If PowerShell blocks script execution, run once (as Administrator):
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```
   Then run `./install.ps1` again.

## Manual Installation (Windows)

```powershell
# Create virtual environment
py -3 -m venv .venv

# Install dependencies
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

# Run app (no terminal attached)
& ".\.venv\Scripts\pythonw.exe" .\main.py
```

## Manual Installation (Linux/macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

## Requirements

- Python 3.7+
- Windows 10+ (primary target), Linux/macOS supported with manual setup
- Python dependencies are listed in `requirements.txt` (`numpy`, `pandas`, `scipy`, `matplotlib`, `PyQt5`)

## Quick Commands

```powershell
# Reinstall/update dependencies in existing environment
& ".\.venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt

# Run without launcher
& ".\.venv\Scripts\pythonw.exe" .\main.py
```

## Uninstall

Delete the project folder (and optionally uninstall Python if you do not need it elsewhere).
