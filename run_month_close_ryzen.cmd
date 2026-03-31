@echo off
setlocal

cd /d C:\MaTrisK-Ryzen\bootstrap\matrisk-bootstrap

set "LOGDIR=logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOGFILE=%LOGDIR%\run_month_close_ryzen.log"
set "PYTHON_EXE=C:\Users\jant1\AppData\Local\Programs\Python\Python313\python.exe"

(
echo =============================================
echo MaTrisK Ryzen month close started
echo Repo: %CD%
echo Time: %DATE% %TIME%
echo Python: %PYTHON_EXE%
echo =============================================

echo [1/6] git pull --rebase
git pull --rebase
if errorlevel 1 (
    echo ERROR: git pull failed
    exit /b 1
)

echo [2/6] promote_closed_months_to_bootstrap.py
"%PYTHON_EXE%" scripts\promote_closed_months_to_bootstrap.py
if errorlevel 1 (
    echo ERROR: promote_closed_months_to_bootstrap.py failed
    exit /b 1
)

echo [3/6] update_monthly_manifest.py
"%PYTHON_EXE%" scripts\update_monthly_manifest.py
if errorlevel 1 (
    echo ERROR: update_monthly_manifest.py failed
    exit /b 1
)

echo [4/6] validate manifest.json
python -m json.tool manifest.json >nul
if errorlevel 1 (
    echo ERROR: manifest.json is invalid
    exit /b 1
)

echo [5/6] git add / commit / push
git add bootstrap manifest.json
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Promote closed monthly bootstrap to historical base"
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

echo =============================================
echo MaTrisK Ryzen month close finished
echo Time: %DATE% %TIME%
echo =============================================
) >> "%LOGFILE%" 2>&1

exit /b %errorlevel%