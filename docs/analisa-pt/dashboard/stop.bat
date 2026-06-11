@echo off
setlocal EnableDelayedExpansion

echo.
echo   Analisa.pt Dashboard - Stopping...
echo   ================================
echo.

set "KILLED=0"
set "SEEN="

REM -- Method 1: Free ports 8080 and 3001 by PID (most reliable when port is bound) ---
echo   [1/4] Scanning ports 8080 and 3001...
for %%P in (8080 3001) do (
    for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%%P " ^| findstr LISTENING') do (
        echo !SEEN! | findstr /C:"|%%I|" >nul 2>&1
        if !ERRORLEVEL! NEQ 0 (
            set "SEEN=!SEEN!|%%I|"
            echo          Port %%P: killing PID %%I...
            taskkill /F /PID %%I >nul 2>&1
            if !ERRORLEVEL! EQU 0 set /a "KILLED+=1"
        )
    )
)

REM -- Method 2: Kill python.exe whose command line contains "api_server.py" ---------
REM -- Catches stuck/zombie processes that aren't bound to a port -------------------
echo   [2/4] Killing api_server.py processes (PowerShell)...
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" ^| Where-Object { $_.CommandLine -like '*api_server.py*' } ^| Select-Object -ExpandProperty ProcessId" 2^>nul') do (
    echo !SEEN! | findstr /C:"|%%I|" >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        set "SEEN=!SEEN!|%%I|"
        echo          api_server.py: killing PID %%I...
        taskkill /F /PID %%I >nul 2>&1
        if !ERRORLEVEL! EQU 0 set /a "KILLED+=1"
    )
)

REM -- Method 3: Kill node.exe running vite (dev server) ---------------------------
echo   [3/4] Killing vite dev server processes (PowerShell)...
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" ^| Where-Object { $_.CommandLine -like '*vite*' } ^| Select-Object -ExpandProperty ProcessId" 2^>nul') do (
    echo !SEEN! | findstr /C:"|%%I|" >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        set "SEEN=!SEEN!|%%I|"
        echo          vite: killing PID %%I...
        taskkill /F /PID %%I >nul 2>&1
        if !ERRORLEVEL! EQU 0 set /a "KILLED+=1"
    )
)

REM -- Method 4: Kill by window title (belt-and-braces) ----------------------------
echo   [4/4] Killing by window title...
REM taskkill returns 0 even when no window matches, so check output for SUCCESS
taskkill /FI "WINDOWTITLE eq Analisa API Server*" /T /F 2>&1 | findstr /C:"SUCCESS" >nul 2>&1
if !ERRORLEVEL! EQU 0 set /a "KILLED+=1"
taskkill /FI "WINDOWTITLE eq Analisa React Dashboard*" /T /F 2>&1 | findstr /C:"SUCCESS" >nul 2>&1
if !ERRORLEVEL! EQU 0 set /a "KILLED+=1"

echo.
if %KILLED% GTR 0 (
    echo   ========================================
    echo   Stopped successfully ^(%KILLED% process^(es^) killed^).
    echo   ========================================
) else (
    echo   No running Analisa.pt processes found.
    echo   If a window is still open, close it manually.
    echo   ========================================
)
echo.

endlocal
exit /b 0
