@echo off
rem Builds dist\FileRing\FileRing.exe, then release\FileRing-Setup.exe if Inno Setup is installed.
rem Creates .venv here on first run.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Setting up Python environment...
    py -3.12 -m venv .venv 2>nul || "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt pyinstaller
".venv\Scripts\python.exe" build.py || exit /b 1

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    "%ISCC%" /Q installer.iss && echo Built release\FileRing-Setup.exe
) else (
    echo Inno Setup not found, skipping the installer. Get it with: winget install JRSoftware.InnoSetup
)
