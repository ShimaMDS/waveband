@echo off
rem Starts Waveband, the damage meter. Close it from its tray icon.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up for the first time...
    python -m venv --system-site-packages .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :fail
)
start "" ".venv\Scripts\pythonw.exe" -X utf8 -m wwmeter run %*
exit /b 0

:fail
echo Setup failed. Python 3.11 or newer needs to be installed and on PATH.
pause
exit /b 1
