@echo off
REM ── refresh_top_findings.bat ─────────────────────────────────────────────
REM Windows Task Scheduler wrapper for the Top Findings background job.
REM Schedule with: schtasks /create /sc daily /st 03:00 /tn "RefreshTopFindings" ^
REM   /tr "D:\vespeiro\docs\analisa-pt\tools\refresh_top_findings.bat"
REM
REM Or run manually: double-click this file.

setlocal
cd /d "%~dp0"

REM Find a Python interpreter. Prefer the one in PATH; fall back to py.exe launcher.
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PY=python"
) else (
    where py >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set "PY=py -3"
    ) else (
        echo [ERROR] Python not found in PATH. Install Python 3.8+ first.
        exit /b 1
    )
)

echo [%date% %time%] Starting top findings refresh...
%PY% _refresh_top_findings.py --once
set RC=%ERRORLEVEL%
echo [%date% %time%] Done. Exit code: %RC%
exit /b %RC%
