import os

content = r"""@echo off
title MQnet Master Control Center
setlocal enabledelayedexpansion

:MENU
cls
set "VENV_STATUS=INACTIVE"
if defined VIRTUAL_ENV (
    set "VENV_STATUS=ACTIVE"
) else (
    python -c "import sys; print('ACTIVE' if 'venv' in sys.executable else 'INACTIVE')" > venv_check.tmp 2>nul
    if exist venv_check.tmp (
        set /p VENV_STATUS=<venv_check.tmp
        del venv_check.tmp
    )
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
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo Setup Completed.
pause
goto MENU

:GIT_PUSH
git add .
set /p msg="Commit Msg: "
if "%msg%"=="" set msg="auto_update"
git commit -m "%msg%"
git push origin main
pause
goto MENU

:DOCKER_REBUILD
docker rm -f mqnet-live
docker build -t mqnet-app:latest .
docker run -d -p 5001:5000 --env-file .env --name mqnet-live mqnet-app:latest
pause
goto MENU

:RUN_LOCAL
if not defined VIRTUAL_ENV call venv\Scripts\activate
set FLASK_DEBUG=1
python app.py
pause
goto MENU

:RUN_TUNNEL
set "RAW_TOKEN="
for /f "tokens=1,2,3,4 delims== " %%a in ('findstr "CLOUDFLARE_TUNNEL_TOKEN" .env') do (
    set "RAW_TOKEN=%%d"
)
if "%RAW_TOKEN%"=="" (
    echo [ERROR] CLOUDFLARE_TUNNEL_TOKEN not found in .env
    pause
    goto MENU
)
echo Running Tunnel for mq.chicvill.store...
cloudflared.exe tunnel run --token %RAW_TOKEN%
pause
goto MENU

:SAAS_CHECK
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
pause
goto MENU

:DB_SEED
start http://localhost:10000/api/internal/seed-demo
pause
goto MENU
"""

# 윈도우 배치는 CRLF(\r\n)와 로컬 인코딩(cp949)이 안전함
try:
    with open("run.bat", "w", encoding="cp949", newline="\r\n") as f:
        f.write(content)
    print("✅ run.bat 파일이 성공적으로 복구되었습니다.")
except Exception as e:
    with open("run.bat", "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)
    print("✅ run.bat 파일이 UTF-8로 복구되었습니다.")
