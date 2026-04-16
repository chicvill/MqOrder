@echo off
title MQnet Master Control Center
setlocal enabledelayedexpansion

:MENU
cls
:: 가상환경 활성화 여부 체크
set "VENV_STATUS=INACTIVE"
if defined VIRTUAL_ENV (
    set "VENV_STATUS=ACTIVE"
) else (
    :: 경로에 venv가 포함되어 있는지 추가 체크
    run_command python -c "import sys; print('ACTIVE' if 'venv' in sys.executable else 'INACTIVE')" > venv_check.tmp
    set /p VENV_STATUS=<venv_check.tmp
    del venv_check.tmp
)

echo ======================================================
echo    MQnet Master Control Center [ VENV: %VENV_STATUS% ]
echo ======================================================
echo  1. Setup VENV (Install dependencies)
echo  2. Github Upload (Push to cloud)
echo  3. Docker Build and Test (Local 5001)
echo  4. Run PC Server (Local 10000)
echo  5. Run Tunnel (mq.chicvill.store)
echo  6. Check SaaS Status (Check Cloud)
echo  7. Check VENV (pip list)
echo  8. Force Reset VENV (Danger!)
echo  9. Sync Knowledge DB (Seed)
echo  0. Exit
echo ======================================================
set /p choice="Enter Number: "

if "%choice%"=="1" goto VENV_SETUP
if "%choice%"=="2" goto GIT_PUSH
if "%choice%"=="3" goto DOCKER_REBUILD
if "%choice%"=="4" goto RUN_LOCAL
if "%choice%"=="5" goto RUN_TUNNEL
if "%choice%"=="6" goto SAAS_CHECK
if "%choice%"=="7" goto VENV_LIST
if "%choice%"=="8" goto VENV_RESET
if "%choice%"=="9" goto DB_SEED
if "%choice%"=="0" exit
goto MENU

:VENV_SETUP
if not exist venv ( python -m venv venv )
:: 가상환경 활체 활성화 (이후 명령들은 가상환경 내에서 실행됨)
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo Setup Completed. VENV is now ACTIVE.
pause
goto MENU

:GIT_PUSH
git add .
set /p msg="Commit Msg: "
if "%msg%"=="" set msg="auto_update_%date%"
git commit -m "%msg%"
git push origin main
echo Upload Success.
pause
goto MENU

:DOCKER_REBUILD
docker rm -f mqnet-live
docker build -t mqnet-app:latest .
docker run -d -p 5001:5000 --env-file .env --name mqnet-live mqnet-app:latest
echo Docker running at http://localhost:5001
pause
goto MENU

:RUN_LOCAL
:: 가상환경 자동 활성화 후 실행
if not defined VIRTUAL_ENV call venv\Scripts\activate
set FLASK_DEBUG=1
python app.py
pause
goto MENU

:RUN_TUNNEL
if not defined VIRTUAL_ENV call venv\Scripts\activate
python update_tunnel.py
pause
goto MENU

:SAAS_CHECK
start https://github.com/chicvill/MqOrder/actions
start https://mq.chicvill.store/api/health
goto MENU

:VENV_LIST
if not defined VIRTUAL_ENV call venv\Scripts\activate
pip list
pause
goto MENU

:VENV_RESET
rmdir /s /q venv
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
echo Reset Done.
pause
goto MENU

:DB_SEED
start http://localhost:10000/api/internal/seed-demo
pause
goto MENU
