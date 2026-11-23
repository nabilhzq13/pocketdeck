@echo off
rem Makes PocketDeck start hidden every time you sign in to Windows, and starts it now.
rem To turn it off again:  autostart.bat off
cd /d "%~dp0"
if /i "%~1"=="off" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0autostart.ps1" -Off
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0autostart.ps1"
)
pause
