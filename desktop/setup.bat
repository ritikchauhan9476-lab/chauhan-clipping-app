@echo off
title Chauhan Clipping - Setup
cd /d "%~dp0"
echo === Chauhan Clipping one-time setup. Needs internet, about 5 to 15 minutes. ===
echo.

rem --- find a good Python. 3.10 to 3.12 works best with all packages.
set "PYCMD="
for %%V in (3.12 3.11 3.10) do (
  if not defined PYCMD (
    py -%%V -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -%%V"
  )
)
if not defined PYCMD (
  where python >nul 2>&1
  if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD goto nopython

%PYCMD% -c "import sys; raise SystemExit(0 if sys.version_info[:2] <= (3,12) else 1)" >nul 2>&1
if errorlevel 1 (
  echo NOTE: your Python is newer than 3.12. Some packages may not install on it.
  echo If setup fails, install Python 3.12 from python.org and run setup.bat again.
  echo.
)

rem --- an old virtual environment made with a too-new Python is rebuilt with the better one
if exist venv\Scripts\python.exe (
  venv\Scripts\python.exe -c "import sys; raise SystemExit(0 if sys.version_info[:2] <= (3,12) else 1)" >nul 2>&1
  if errorlevel 1 (
    %PYCMD% -c "import sys; raise SystemExit(0 if sys.version_info[:2] <= (3,12) else 1)" >nul 2>&1
    if not errorlevel 1 (
      echo The old virtual environment uses a too-new Python. Rebuilding it...
      rmdir /s /q venv
    )
  )
)
if not exist venv\Scripts\python.exe (
  echo Creating the virtual environment...
  %PYCMD% -m venv venv
  if errorlevel 1 goto novenv
)

call venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto nopkgs

echo.
call install_ai.bat nopause

where ffmpeg >nul 2>&1
if errorlevel 1 (
  where winget >nul 2>&1
  if not errorlevel 1 (
    echo.
    echo FFmpeg was not found. Installing it with winget...
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    echo FFmpeg is installed. Restart the PC once so that Windows can find it.
  ) else (
    echo.
    echo NOTE: FFmpeg was not found. Install the full build from https://www.gyan.dev/ffmpeg/builds/ and restart the PC.
  )
)
echo.
echo Setup complete. Double-click run.bat to start the app.
pause
exit /b 0

:nopython
echo Python was not found.
where winget >nul 2>&1
if not errorlevel 1 (
  echo Installing Python 3.12 with winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python 3.12 is installed. CLOSE this window and double-click setup.bat again.
) else (
  echo Install Python 3.12 from python.org and tick Add python.exe to PATH. Then run setup.bat again.
)
pause
exit /b 1

:novenv
echo Could not create the virtual environment.
pause
exit /b 1

:nopkgs
echo Packages could not be installed. Check your internet connection and run setup.bat again.
pause
exit /b 1
