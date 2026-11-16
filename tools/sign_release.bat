@echo off
rem Sign a release's SHA256SUMS.txt with the release key, then check the signature.
rem Drag SHA256SUMS.txt onto this file, or double-click it and drop the file in when asked.
rem The passphrase is asked for by tools\release_key.py; it is not shown or written anywhere.
setlocal
cd /d "%~dp0.."
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo The project's Python is missing: run run.bat once first.
    goto :end
)

set "SUMS=%~1"
if "%SUMS%"=="" (
    echo Drag the release's SHA256SUMS.txt into this window, then press Enter:
    set /p "SUMS="
)
if not defined SUMS (
    echo No file given.
    goto :end
)
rem a dragged path comes in quotes
set "SUMS=%SUMS:"=%"
if not exist "%SUMS%" (
    echo Not found: %SUMS%
    goto :end
)

echo.
echo Signing %SUMS%
echo ----
type "%SUMS%"
echo ----
echo.
"%PY%" tools\release_key.py sign "%SUMS%" || goto :failed
"%PY%" tools\release_key.py verify "%SUMS%" || goto :failed
echo.
echo Signed: %SUMS%.sig
echo Upload SHA256SUMS.txt and SHA256SUMS.txt.sig with the release.
goto :end

:failed
echo.
echo Signing did not complete (wrong passphrase, or the key file could not be read). Nothing was published.

:end
echo.
pause
