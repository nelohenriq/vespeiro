@echo off
echo.
echo   Analisa.pt Dashboard - Starting...
echo   ================================
echo.

REM -- Port conflict check -----------------------------------------
netstat -ano | findstr :8080 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   ERROR: Port 8080 is already in use.
    echo   Run stop.bat first, or close the other process.
    pause
    exit /b 1
)
netstat -ano | findstr :3001 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   ERROR: Port 3001 is already in use.
    echo   Run stop.bat first, or close the other process.
    pause
    exit /b 1
)

echo   [1/2] Starting API server on port 8080...
start "Analisa API Server" cmd /k "cd /d %~dp0..\tools && python api_server.py --port 8080"
echo   Waiting for API server to initialize (loading 6 databases)...
timeout /t 12 /nobreak >nul
echo   [2/2] Starting React dev server on port 3001...
start "Analisa React Dashboard" cmd /k "cd /d %~dp0 && npm run dev"
timeout /t 5 /nobreak >nul
echo.
echo   ========================================
echo   Dashboard:  http://localhost:3001
echo   API Server: http://localhost:8080
echo   ========================================
echo.
echo   Close both cmd windows to stop. Or run stop.bat.
echo.
