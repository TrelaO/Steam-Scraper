@echo off
setlocal

cd /d "%~dp0"

echo Starting Steam AI-ETL (first run can take a few minutes to build)...
docker compose up -d --build
if errorlevel 1 (
    echo.
    echo Could not start the app. Is Docker Desktop installed and running?
    pause
    exit /b 1
)

echo Waiting for the app to respond on http://localhost:8000 ...
set count=0

:wait
set /a count+=1
curl -s -o nul http://localhost:8000
if not errorlevel 1 goto ready
if %count% GEQ 90 goto timeout
timeout /t 2 /nobreak >nul
goto wait

:ready
start "" http://localhost:8000
goto end

:timeout
echo App did not respond in time - opening the page anyway.
echo If it does not load, run: docker compose logs
start "" http://localhost:8000

:end
endlocal
