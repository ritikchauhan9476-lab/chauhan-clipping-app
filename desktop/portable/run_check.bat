@echo off
title Chauhan Clipping - check
cd /d "%~dp0"
set "PYTHONNOUSERSITE=1"
"%~dp0python\python.exe" selfcheck.py
pause
