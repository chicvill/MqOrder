@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
title MQnet Control Center

:MENU
cls
echo.
echo  ======================================================
echo     MQnet Master Control Center
echo  ======================================================
echo   1. Setup VENV  (Install dependencies)
echo   2. Github Upload  (Push to cloud)
echo   3. Docker Build and Test  (Local 5001)
echo   4. Run PC Server  (Local 10000)
echo   0. Exit
echo  ======================================================
echo.
set /p choice="  Enter Number: "

if "%choice%"=="1" goto VENV_SETUP
if "%choice%"=="2" goto GIT_PUSH
if "%choice%"=="3" goto DOCKER_RUN
if "%choice%"=="4" goto RUN_LOCAL
if "%choice%"=="0" exit
goto MENU

:VENV_SETUP
echo.
echo  [VENV] Setting up virtual environment...
if not exist ".venv" (
    python -m venv .venv
    echo  [VENV] Created .venv
)
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\pip.exe" install -r requirements.txt
echo  [VENV] Done.
pause
goto MENU

:GIT_PUSH
echo.
echo  [GIT] Pushing to Github...
git add .
git commit -m "auto: %date% %time%"
git push
echo  [GIT] Done.
pause
goto MENU

:DOCKER_RUN
echo.
echo  [DOCKER] Building and running on port 5001...
docker build -t mqnet .
docker run -p 5001:10000 --env-file .env mqnet
pause
goto MENU

:RUN_LOCAL
echo.
echo  [SERVER] Starting MQnet on http://localhost:10000
echo  --------------------------------------------------------
".venv\Scripts\python.exe" app.py
echo  --------------------------------------------------------
echo  [SERVER] Stopped. Check messages above.
pause
goto MENU
