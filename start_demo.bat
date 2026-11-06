@echo off
setlocal
cd /d "%~dp0"
title Q-MigrateAI demo
echo.
echo   Q-MigrateAI - local demo on this laptop
echo   ---------------------------------------
echo.

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :nopython

if not exist ".venv\Scripts\python.exe" (
  echo   First start: creating a private Python environment in the .venv folder...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
set "VPY=.venv\Scripts\python.exe"

if not exist ".venv\packages-installed-v4.txt" (
  echo   Installing the packages once. This needs internet and takes a few minutes...
  "%VPY%" -m pip install --upgrade pip
  "%VPY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
  echo installed> ".venv\packages-installed-v4.txt"
)

echo.
echo   Starting. The very first start measures real public websites (needs internet)
echo   and trains the AI models, which takes a minute or two. Your browser opens by itself.
echo.
echo   Address:   http://localhost:8002
echo   Project data (view, correct, download):  http://localhost:8002/project-data/
echo   Password for every demo login:  QuantumDemo!2026
echo   Keep this window open during the demo. Press Ctrl+C to stop.
echo.
start "" /b cmd /c "ping -n 9 127.0.0.1 >nul & start "" http://localhost:8002"
"%VPY%" -m uvicorn qmigrate.server.app:app --host 127.0.0.1 --port 8002
goto :eof

:nopython
echo   Python 3.10 or newer was not found.
echo   Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo   then double-click start_demo.bat again.
pause
exit /b 1

:fail
echo.
echo   Something went wrong. Read the messages above, or delete the .venv folder and try again.
pause
exit /b 1
