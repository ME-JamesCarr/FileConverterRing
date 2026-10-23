@echo off
rem Starts FileRing. On first run it creates a .venv here and installs the requirements.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo First run: setting up Python environment...
    py -3.12 -m venv .venv 2>nul || "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" main.py
