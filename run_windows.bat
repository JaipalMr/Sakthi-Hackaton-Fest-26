@echo off
REM One-click start for Windows: sets everything up the first time, then opens backend + frontend.
REM Both servers run in their own windows; if the "Backend API" window shows an error, that is the reason the page says "API offline".
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  pause & exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js 18+ is required: https://nodejs.org/
  pause & exit /b 1
)

REM ---- Python environment (the marker file means a half-finished install is redone instead of being trusted) ----
if not exist .venv\Scripts\activate.bat (
  echo Creating Python environment...
  python -m venv .venv
  if errorlevel 1 ( echo Could not create the virtual environment. & pause & exit /b 1 )
)
call .venv\Scripts\activate.bat
if not exist .venv\.deps_ok (
  echo Installing Python packages - this can take a few minutes the first time...
  python -m pip install --upgrade pip >nul 2>nul
  python -m pip install -r requirements.txt
  if errorlevel 1 ( echo Installing Python packages failed - see the messages above. & pause & exit /b 1 )
  echo ok> .venv\.deps_ok
)

REM ---- Frontend packages ----
if not exist frontend\node_modules\.bin (
  echo Installing frontend packages...
  pushd frontend
  call npm install
  if errorlevel 1 ( popd & echo npm install failed - see the messages above. & pause & exit /b 1 )
  popd
)

REM ---- Backend (own window, kept open so errors stay visible) ----
echo Starting backend. The first start can take about a minute while the model is prepared...
start "Backend API" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"

set tries=0
:wait
set /a tries+=1
powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 2).StatusCode}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto ready
if %tries% geq 90 goto failed
timeout /t 2 >nul
goto wait

:failed
echo The backend did not become ready within 3 minutes. Look at the "Backend API" window for the error message.
pause & exit /b 1

:ready
echo Backend is ready.
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 4 >nul
start http://127.0.0.1:5173
