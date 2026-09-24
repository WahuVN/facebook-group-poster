@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo [Loi] Khong tim thay Python launcher "py".
  echo Cai Python 3.11+ roi chay lai file nay.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [i] Tao virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo [Loi] Khong tao duoc virtual environment.
    pause
    exit /b 1
  )
)

echo [i] Cai runtime theo lock file exact...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-runtime.lock
if errorlevel 1 (
  echo [Loi] Cai dependency that bai.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip check
if errorlevel 1 (
  echo [Loi] pip check khong dat.
  pause
  exit /b 1
)

if /I "%~1"=="--with-playwright-browser" (
  echo [i] Cai Playwright Chromium theo revision cua Playwright 1.54.0...
  ".venv\Scripts\python.exe" -m playwright install chromium
  if errorlevel 1 (
    echo [Loi] Cai Playwright Chromium that bai.
    pause
    exit /b 1
  )
) else (
  echo [i] Khong tu tai browser. Neu can Playwright Chromium:
  echo     Setup_FB_Tool.bat --with-playwright-browser
)

echo [OK] Runtime da san sang.
pause
