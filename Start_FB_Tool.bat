@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo [Loi] Khong tim thay Python launcher py.
  echo Hay cai Python 3.11+ roi mo lai.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [i] Tao moi virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo [Loi] Khong tao duoc virtual environment.
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat

echo [i] Cai dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [Loi] Cai package that bai.
  pause
  exit /b 1
)

echo [i] Cai Playwright Chromium (lan dau co the hoi lau)...
python -m playwright install chromium

python fb_group_poster_gui.py
if errorlevel 1 (
  echo.
  echo [Loi] Tool da dung voi ma loi !errorlevel!.
  echo Kiem tra log tren cua so GUI/terminal.
)

pause
