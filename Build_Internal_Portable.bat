@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Loi] Chua co .venv. Chay Setup_FB_Tool.bat truoc.
  pause
  exit /b 1
)

echo [i] Cai build tool theo lock file exact...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-build.lock
if errorlevel 1 (
  echo [Loi] Cai build dependency that bai.
  pause
  exit /b 1
)

set "OUT=%~1"
if "%OUT%"=="" set "OUT=%CD%\dist_internal"

echo [i] Build internal NOT_PUBLIC_RELEASE...
".venv\Scripts\python.exe" -B package_portable.py --output "%OUT%"
if errorlevel 1 (
  echo [Loi] Build/smoke that bai.
  pause
  exit /b 1
)

echo [OK] Build + smoke PASS. Artifact chi dung noi bo cho den khi owner dong legal gate.
pause
