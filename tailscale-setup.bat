@echo off
rem Sets up Tailscale so PocketDeck works on any network. Asks for administrator rights.
cd /d "%~dp0"
net session >nul 2>&1 || (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tailscale-setup.ps1"
echo.
pause
