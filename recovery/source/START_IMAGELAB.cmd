@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul || (
  echo Python 3.13 is required.
  pause
  exit /b 1
)
start "ImageLab" /min python bootstrap.py
endlocal
