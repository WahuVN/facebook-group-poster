@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Loi] Chua co runtime da khoa dependency.
  echo Chay Setup_FB_Tool.bat mot lan truoc khi mo tool.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -B portable_launcher.py
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo [Loi] Tool dung voi ma loi %EXITCODE%.
  echo Chay: ".venv\Scripts\python.exe" -B portable_launcher.py --preflight
  echo de xem kiem tra runtime.
)

pause
exit /b %EXITCODE%
