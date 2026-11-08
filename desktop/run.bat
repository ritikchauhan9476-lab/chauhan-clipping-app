@echo off
title Chauhan Clipping
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo First run: installing everything, this can take a few minutes...
  call setup.bat
)
call venv\Scripts\activate
python -c "import customtkinter, PIL, numpy" >nul 2>&1
if errorlevel 1 (
  echo Installing missing packages...
  python -m pip install -r requirements.txt
)
python app.py
if errorlevel 1 (
  echo.
  echo The app stopped with an error. Copy the message above and send it to us.
  pause
)
