@echo off
setlocal

cd /d "%~dp0"

if not exist logs mkdir logs
set "LOGFILE=%CD%\logs\run_update_live_ryzen.log"
set "PYTHON_EXE=C:\Users\jant1\AppData\Local\Programs\Python\Python313\python.exe"

(
echo =========================================
echo MaTrisK Ryzen live update started
echo Repo: %CD%
echo Time: %DATE% %TIME%
echo Python: %PYTHON_EXE%
echo =========================================

echo [1/8] git pull --rebase
git pull --rebase
if errorlevel 1 (
    echo ERROR: git pull failed
    exit /b 1
)

echo [2/8] update_live_local.py
"%PYTHON_EXE%" scripts\update_live_local.py
if errorlevel 1 (
    echo ERROR: update_live_local.py failed
    exit /b 1
)

echo [3/8] build_live_backlog.py
python scripts\build_live_backlog.py
if errorlevel 1 (
    echo ERROR: build_live_backlog.py failed
    exit /b 1
)

echo [4/8] build_monthly_bootstrap.py
python scripts\build_monthly_bootstrap.py
if errorlevel 1 (
    echo ERROR: build_monthly_bootstrap.py failed
    exit /b 1
)

echo [5/8] update_monthly_manifest.py
python scripts\update_monthly_manifest.py
if errorlevel 1 (
    echo ERROR: update_monthly_manifest.py failed
    exit /b 1
)

echo [6/8] validate live\latest.json
python -m json.tool live\latest.json >nul
if errorlevel 1 (
    echo ERROR: live\latest.json is invalid
    exit /b 1
)

echo [7/8] validate manifest.json
python -m json.tool manifest.json >nul
if errorlevel 1 (
    echo ERROR: manifest.json is invalid
    exit /b 1
)


echo [8/8] git add live\latest.json live\deltas bootstrap-monthly manifest.json scripts\build_live_backlog.py scripts\build_monthly_bootstrap.py scripts\update_monthly_manifest.py run_update_live_ryzen.cmd

git diff --cached --quiet
if errorlevel 1 (
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