@echo off
REM Starts the backend (FastAPI, port 8000) and frontend (Vite, port 5173),
REM each in its own window. Close those windows to stop the servers.

setlocal

echo Starting backend...
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Backend virtualenv not found. Create it first:
    echo   cd backend
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)
start "Backend - FastAPI :8000" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo Starting frontend...
cd /d "%~dp0frontend"
if not exist "node_modules" (
    echo Installing frontend packages, this runs once...
    call npm install
)
start "Frontend - Vite :5173" cmd /k "npm run dev -- --port 5173"

echo.
echo Backend API docs: http://localhost:8000/api/docs
echo Frontend app:     http://localhost:5173
echo.
pause
endlocal


terminal command to run Backend: uvicorn app.main:app --port 8000 --reload
terminal command to run Frontend: npm run dev