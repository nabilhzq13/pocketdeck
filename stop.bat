@echo off
rem Stops PocketDeck when it runs hidden in the background (see autostart.bat).
setlocal
cd /d "%~dp0"
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python was not found.
  pause
  exit /b 1
)
%PY% server.py --stop
timeout /t 3 >nul
