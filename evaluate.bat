@echo off
rem Thesis evaluation: quantum deadlines and explanations vs the rule baseline.
rem Run start_demo.bat once first, so the real websites have been measured.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_demo.bat first.
  exit /b 1
)
.venv\Scripts\python -m qmigrate.research.evaluate %*
echo.
echo Results are in the data\research folder.
pause
