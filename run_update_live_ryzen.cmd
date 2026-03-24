@echo off
setlocal

cd /d "%~dp0"

if not exist logs mkdir logs
set LOGFILE=%CD%\logs\run_update_live_ryzen.log

(
echo =========================================
echo MaTrisK Ryzen live update started
echo Repo: %CD%
echo Time: %DATE% %TIME%
echo =========================================

set PYTHON_CMD=python

echo [1/5] git pull --rebase
git pull --rebase
if errorlevel 1 (
    echo ERROR: git pull failed
    exit /b 1
)

echo [2/5] update_live_local.py
%PYTHON_CMD% scripts\update_live_local.py
if errorlevel 1 (
    echo ERROR: update_live_local.py failed
    exit /b 1
)

echo [3/5] build_live_backlog.py
%PYTHON_CMD% scripts\build_live_backlog.py
if errorlevel 1 (
    echo ERROR: build_live_backlog.py failed
    exit /b 1
)

echo [4/5] validate live\latest.json
%PYTHON_CMD% -m json.tool live\latest.json > nul
if errorlevel 1 (
    echo ERROR: live\latest.json is invalid
    exit /b 1
)

echo [5/5] git add / commit / push
git add live\latest.json live\deltas scripts\build_live_backlog.py scripts\update_live_local.py run_update_live_ryzen.cmd

git diff --cached --quiet
if not errorlevel 1 (
    git commit -m "Auto update live latest and monthly deltas"
    if errorlevel 1 (
        echo ERROR: git commit failed
        exit /b 1
    )

    git push
    if errorlevel 1 (
        echo ERROR: git push failed
        exit /b 1
    )

    echo OK: changes pushed to GitHub
) else (
    echo OK: no changes to commit
)

echo =========================================
echo MaTrisK Ryzen live update finished
echo Time: %DATE% %TIME%
echo =========================================
) >> "%LOGFILE%" 2>&1

exit /b %errorlevel%