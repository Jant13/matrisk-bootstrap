@echo off
title MaTrisK Toshiba Collector

cd /d C:\MaTrisK\matrisk-bootstrap

echo.
echo [1/5] Actualizando repo...
git pull origin main

echo.
echo [2/5] Ejecutando recolector...
python scripts\update_live_local.py

echo.
echo [3/5] Preparando latest.json...
git add live\latest.json

git diff --cached --quiet
if %errorlevel%==0 (
    echo.
    echo No hay cambios en live\latest.json.
    pause
    exit /b 0
)

echo.
echo [4/5] Guardando cambios...
git commit -m "Auto-update latest.json from Toshiba"

echo.
echo [5/5] Subiendo a GitHub...
git push origin main

echo.
echo Proceso finalizado.
pause