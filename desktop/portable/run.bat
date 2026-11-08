@echo off
title Chauhan Clipping
cd /d "%~dp0"
set "PATH=%~dp0ffmpeg;%PATH%"
set "PYTHONNOUSERSITE=1"
"%~dp0python\python.exe" app.py
if errorlevel 1 (
  echo.
  echo The app stopped with an error. Copy the message above and send it to us.
  pause
)
