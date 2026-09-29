@echo off
setlocal EnableExtensions
chcp 65001 >nul
title MicroDramaGenerator 安裝
cd /d "%~dp0"

echo ============================================
echo   MicroDramaGenerator  一鍵安裝
echo ============================================
echo 會做這些事：
echo   1. 沒有 Python 3.10+ 時，用 winget 安裝
echo   2. 建立 .venv
echo   3. 安裝 CUDA 版 PyTorch，失敗再改 CPU 版
echo   4. 安裝 requirements.txt 與 requirements-diffusers.txt
echo   5. 建立 output、data\stories、data\drafts、data\video
echo   6. 用 scripts\build_preset_stories.py 重寫內建短劇
echo.
echo 不下載 ComfyUI、Diffusers 模型、Ollama、VoxCPM。
echo 模型路徑請改 config.yaml。可重複執行。
echo.

where winget >nul 2>&1
if errorlevel 1 (
  echo [提示] 沒有 winget。請自行安裝 Python 3.10+ 並加入 PATH。
) else (
  call :ensure_winget Python.Python.3.12 python
  call :refresh_path
)

call :find_python
if not defined PY (
  echo ERROR: 找不到 Python。請安裝 3.10+ 後重跑。
  echo   https://www.python.org/downloads/
  pause
  exit /b 1
)
echo [Python] %PY%
"%PY%" -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 (
  echo ERROR: 需要 Python 3.10 以上
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [venv] 建立 .venv
  "%PY%" -m venv .venv
  if errorlevel 1 (
    echo ERROR: 建立 .venv 失敗
    pause
    exit /b 1
  )
)
set "VPY=%cd%\.venv\Scripts\python.exe"

echo [pip] 升級 pip
"%VPY%" -m pip install -U pip
if errorlevel 1 (
  echo ERROR: pip 升級失敗
  pause
  exit /b 1
)

echo [pip] 安裝 CUDA PyTorch（cu128）。沒有 NVIDIA 或驅動太舊會失敗，再改裝預設版
"%VPY%" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 (
  echo [pip] CUDA 版失敗，改裝預設 torch
  "%VPY%" -m pip install torch torchvision torchaudio
  if errorlevel 1 (
    echo ERROR: PyTorch 安裝失敗
    pause
    exit /b 1
  )
)

echo [pip] 本專案套件
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: requirements.txt 安裝失敗
  pause
  exit /b 1
)
"%VPY%" -m pip install -r requirements-diffusers.txt
if errorlevel 1 (
  echo ERROR: requirements-diffusers.txt 安裝失敗
  pause
  exit /b 1
)

echo [目錄] output、data\stories、data\drafts、data\video
if not exist "output" mkdir "output"
if not exist "data\stories" mkdir "data\stories"
if not exist "data\drafts" mkdir "data\drafts"
if not exist "data\video" mkdir "data\video"
if not exist "data\sounds\female" mkdir "data\sounds\female"
if not exist "data\sounds\male" mkdir "data\sounds\male"

echo [短劇] 重寫 data\preset_stories.json
"%VPY%" scripts\build_preset_stories.py
if errorlevel 1 (
  echo ERROR: 內建短劇寫入失敗
  pause
  exit /b 1
)

if not exist "data\characters.json" (
  echo.
  echo ERROR: 找不到 data\characters.json
  echo 伺服器啟動必讀這個角色清單。版控有附上一份；若被刪了請從備份放回。
  pause
  exit /b 1
)

if not exist "data\default_male.png" (
  echo [提示] 沒有 data\default_male.png。男角色留空時會改為現場生圖。
)

echo.
echo [GPU]
"%VPY%" -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"

echo.
echo ============================================
echo   安裝完成。下一步：
echo   1. 確認 ComfyUI 在 http://127.0.0.1:8188
echo   2. 依 README.md 檢查 config.yaml 的模型路徑
echo   3. 雙擊 start.bat ，開啟 http://127.0.0.1:8620
echo ============================================
pause
exit /b 0

:ensure_winget
where %2 >nul 2>&1
if not errorlevel 1 (
  echo [已有] %2
  goto :eof
)
echo [winget] 安裝 %1
winget install -e --id %1 --accept-package-agreements --accept-source-agreements
goto :eof

:refresh_path
set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts"
set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts"
goto :eof

:find_python
set "PY="
where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
    set "PY=%%i"
    goto :eof
  )
)
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%i in ('where python') do (
    echo %%i | find /i "WindowsApps" >nul
    if errorlevel 1 (
      set "PY=%%i"
      goto :eof
    )
  )
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  goto :eof
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  goto :eof
)
goto :eof
