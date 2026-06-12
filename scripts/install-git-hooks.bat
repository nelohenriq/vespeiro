@echo off
REM Install the project's git hooks by pointing core.hooksPath at the
REM tracked .githooks\ directory.
REM
REM Idempotent: safe to run multiple times.
REM
REM Usage:
REM   scripts\install-git-hooks.bat

setlocal

REM Resolve the repo root (handles being called from any CWD)
for /f "delims=" %%i in ('git rev-parse --show-toplevel') do set REPO_ROOT=%%i
set HOOKS_DIR=%REPO_ROOT%\.githooks
set HOOK_FILE=%HOOKS_DIR%\pre-commit

if not exist "%HOOK_FILE%" (
    echo ERROR: %HOOK_FILE% not found.
    echo Are you in a clone where the hook has been committed?
    exit /b 1
)

REM Point git at the tracked hooks dir
git config core.hooksPath "%HOOKS_DIR%"

echo Installed git hooks:
echo    core.hooksPath = %HOOKS_DIR%
echo.
echo Hook: %HOOK_FILE%
echo Test it: try to commit a file with a raw sqlite3.connect^(^) call
echo          ^(should be rejected with a clear error message^).

endlocal
