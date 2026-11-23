@echo off
rem PocketDeck: double-click to start. The first run installs what it needs (internet required).
setlocal
cd /d "%~dp0"
title PocketDeck

call :find_python
if not defined PY goto :no_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Your Python is too old. PocketDeck needs Python 3.11 or newer.
  goto :manual_python
)

rem Packages are built for one Python version, so reinstall them when Python changes.
for /f "delims=" %%v in ('%PY% -c "import sys; print(sys.version_info[0], sys.version_info[1], sep=chr(46))"') do set "PYVER=%%v"
set "STAMP=.deps\installed-for-python.txt"
set "HAVE="
if exist "%STAMP%" set /p HAVE=<"%STAMP%"
if not "%HAVE%"=="%PYVER%" (
  echo Installing PocketDeck's packages for Python %PYVER%. This happens once and takes a minute...
  if exist .deps rmdir /s /q .deps
  %PY% -m pip install --disable-pip-version-check -q --target .deps -r requirements.txt
  if errorlevel 1 goto :install_failed
  >"%STAMP%" echo %PYVER%
)

%PY% server.py %*
if errorlevel 1 pause
exit /b

:find_python
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3" && goto :eof
python -c "import sys" >nul 2>&1 && set "PY=python"
goto :eof

:no_python
echo PocketDeck needs Python 3.11 or newer, and it is not installed.
where winget >nul 2>&1 || goto :manual_python
choice /m "Install Python 3.13 now with winget"
if errorlevel 2 goto :manual_python
winget install -e --id Python.Python.3.13 --scope user --accept-source-agreements --accept-package-agreements
echo.
echo Python is installed. Close this window and double-click start.bat again.
pause
exit /b 0

:manual_python
echo Get it from https://www.python.org/downloads/ then run start.bat again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:install_failed
echo Installing the packages failed. Check your internet connection and run start.bat again.
if exist .deps rmdir /s /q .deps
pause
exit /b 1
