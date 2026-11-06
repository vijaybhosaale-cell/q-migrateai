@echo off
cd /d "%~dp0"
echo This deletes the local demo database so the next start begins from the freshly discovered state.
echo (Stop start_demo.bat first with Ctrl+C.)
choice /m "Delete the demo data now"
if errorlevel 2 exit /b 0
if exist "data\qmigrate.db" del /q "data\qmigrate.db"
if exist "data\qmigrate.db-wal" del /q "data\qmigrate.db-wal"
if exist "data\qmigrate.db-shm" del /q "data\qmigrate.db-shm"
echo Done. Double-click start_demo.bat to start again.
pause
