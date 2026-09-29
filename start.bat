@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MicroDramaGenerator

set "VPY="
if exist "%~dp0.venv\Scripts\python.exe" set "VPY=%~dp0.venv\Scripts\python.exe"
if not defined VPY if exist "%~dp0..\AnimGenerator\.venv\Scripts\python.exe" set "VPY=%~dp0..\AnimGenerator\.venv\Scripts\python.exe"
if not defined VPY (
  where py >nul 2>&1
  if not errorlevel 1 set "VPY=py -3"
)
if not defined VPY (
  where python >nul 2>&1
  if not errorlevel 1 set "VPY=python"
)
if not defined VPY (
  echo Python not found. Install Python 3, or create .venv in this folder.
  echo   py -3 -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

echo ============================================
echo   MicroDramaGenerator
echo   http://127.0.0.1:8620
echo ============================================
echo python: %VPY%

call :port_up 8188
if errorlevel 1 (
  echo [WARN] ComfyUI is not on 8188. Start it before generating video.
) else (
  echo [OK] ComfyUI on 8188
)

call :port_up 11434
if errorlevel 1 (
  where ollama >nul 2>&1
  if not errorlevel 1 (
    echo [START] Ollama
    start "Ollama" /min ollama serve
  ) else (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
      echo [START] Ollama
      start "Ollama" /min "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve
    ) else (
      echo [INFO] Ollama not found. Built-in stories still work.
    )
  )
) else (
  echo [OK] Ollama on 11434
)

echo [START] http://127.0.0.1:8620
start "" /b cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8620"
%VPY% server.py
if errorlevel 1 (
  echo.
  echo server.py failed. Check:
  echo   1. pip install -r requirements.txt
  echo   2. port 8620 already in use
)
echo.
pause
exit /b 0

:port_up
powershell -NoProfile -Command "try { $t=New-Object Net.Sockets.TcpClient; $t.Connect('127.0.0.1',%1); $t.Close(); exit 0 } catch { exit 1 }"
goto :eof
