@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating Python 3.12 environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto error
  echo [2/3] Installing dependencies...
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto error
) else (
  echo Environment ready.
)
echo [3/3] Initializing database and starting workstation...
.venv\Scripts\python.exe scripts\init_db.py
if errorlevel 1 goto error
start "" "http://127.0.0.1:8000"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto end
:error
echo Startup failed. Review the error above and README.md.
pause
:end
