@echo off
title Chauhan Clipping - AI speech detector
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo Run setup.bat first.
  if "%~1"=="" pause
  exit /b 1
)
call venv\Scripts\activate
echo Installing the AI speech detector: Silero VAD through onnxruntime. No PyTorch needed.
python -m pip install onnxruntime
if errorlevel 1 goto fail
python -m pip install --no-deps silero-vad
if errorlevel 1 goto fail
python -c "import glob, os, importlib.util as u; s=u.find_spec('silero_vad'); d=list(s.submodule_search_locations)[0]; f=glob.glob(os.path.join(d,'**','*.onnx'), recursive=True); print('Model files:', f); raise SystemExit(0 if f else 1)"
if errorlevel 1 goto fail
echo.
echo AI speech detector installed.
if "%~1"=="" pause
exit /b 0

:fail
echo.
echo The AI speech detector could not be installed. The app still works with its built-in detector.
echo If you want to try again later, double-click install_ai.bat.
if "%~1"=="" pause
exit /b 1
