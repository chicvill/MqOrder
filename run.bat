@echo off
:: 한글 깨짐 방지를 위한 UTF-8 코드페이지 설정
chcp 65001 >nul
title MQnet 통합 제어 센터 (Control Center)
setlocal enabledelayedexpansion

:MENU
cls
echo ======================================================
echo    MQnet SaaS 플랫폼 - 통합 개발 및 운영 메뉴
echo ======================================================
echo  1. 가상환경 설정/업데이트 (라이브러리 동기화)
echo  2. GitHub 업로드 (SaaS 서비스 실시간 갱신)
echo  3. Docker 빌드 및 테스트 (로컬 5001번 포트)
echo  4. 로컬 PC 서버 실행 (로컬 10000번 포트)
echo  5. PC 도메인 터널 실행 (mq.chicvill.store 연결)
echo  6. SaaS 서버 상태 확인 (Render-Docker-Supabase)
echo  7. 패키지 설치 목록 확인 (VENV 점검)
echo  8. [주의] 가상환경 강제 초기화 (VENV 재생성)
echo  9. Knowledge DB 동기화 (데모 데이터 생성)
echo  0. 종료
echo ======================================================
set /p choice="원하는 작업 번호를 입력하고 엔터를 누르세요: "

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
echo [1] 가상환경(VENV) 라이브러리를 업데이트합니다...
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate
pip install -r requirements.txt
echo ✅ 모든 라이브러리 업데이트가 완료되었습니다.
pause
goto MENU

:GIT_PUSH
echo [2] GitHub에 코드를 전송하여 실제 서버를 갱신합니다...
git add .
set /p commit_msg="업데이트 내용 입력 (엔터 시 자동 생성): "
if "!commit_msg!"=="" set commit_msg="업데이트: %date% %time%"
git commit -m "!commit_msg!"
git push origin main
echo ✅ 업로드 성공! 잠시 후 실제 서비스(mq.chicvill.store)에 반영됩니다.
pause
goto MENU

:DOCKER_REBUILD
echo [3] Docker 컨테이너 서버를 빌드 및 실행합니다...
docker rm -f mqnet-live
docker build -t mqnet-app:latest .
docker run -d -p 5001:5000 --env-file .env --name mqnet-live mqnet-app:latest
echo ✅ 완료! 브라우저에서 http://localhost:5001 로 접속하세요.
pause
goto MENU

:RUN_LOCAL
echo [4] 로컬 PC 서버를 실행합니다 (디버깅용)...
call venv\Scripts\activate
set FLASK_DEBUG=1
python app.py
pause
goto MENU

:RUN_TUNNEL
echo [5] 로컬 PC 서비스를 외부 도메인으로 임시 연결합니다...
call venv\Scripts\activate
python update_tunnel.py
pause
goto MENU

:SAAS_CHECK
echo [6] 클라우드 운영 서버 상태를 확인합니다...
start https://github.com/chicvill/MqOrder/actions
start https://mq.chicvill.store/api/health
echo ✅ 배포 현황 및 헬스 체크 페이지를 브라우저로 열었습니다.
pause
goto MENU

:VENV_LIST
echo [7] 현재 설치된 파이썬 패키지 목록입니다.
call venv\Scripts\activate
pip list
pause
goto MENU

:VENV_RESET
echo [8] 가상환경(VENV) 폴더를 삭제하고 처음부터 다시 만듭니다.
set /p confirm="진행하시겠습니까? (Y/N): "
if /i "%confirm%"=="Y" (
    rmdir /s /q venv
    python -m venv venv
    call venv\Scripts\activate
    pip install -r requirements.txt
    echo ✅ 초기화가 성공적으로 완료되었습니다.
)
pause
goto MENU

:DB_SEED
echo [9] 데이터베이스에 데모 데이터를 채워 넣습니다...
start http://localhost:10000/api/internal/seed-demo
echo ✅ 동기화 요청이 완료되었습니다. (서버가 켜져 있어야 합니다)
pause
goto MENU
