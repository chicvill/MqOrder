@echo off
setlocal enabledelayedexpansion
cd /d %~dp0

:MENU
cls
echo ===================================================
echo   [MQnet] Unified Server Manager
echo ===================================================
echo  1. Local Test Mode (Port 10000, Debug ON)
echo  2. Domain Connection (External Access, run_domain.py)
echo  3. Normal Server Run (Standard Environment)
echo  4. [Force Reset] Recreate .venv (Full Repair)
echo  5. [Status Check] VENV Info ^& Update Libs
echo  6. [Sync Knowledge] Update Knowledge DB (Seed)
echo  0. Exit
echo ===================================================
set /p choice="Enter choice (0-6): "

if "%choice%"=="1" goto LOCAL_RUN
if "%choice%"=="2" goto DOMAIN_RUN
if "%choice%"=="3" goto NORMAL_RUN
if "%choice%"=="4" goto SETUP_VENV
if "%choice%"=="5" goto VENV_STATUS
if "%choice%"=="6" goto SEED_KNOWLEDGE
if "%choice%"=="0" exit
goto MENU

:LOCAL_RUN
echo [Info] Preparing Local Test Mode...
call :CHECK_VENV
if errorlevel 1 pause & goto MENU
echo [Auto-Sync] Updating knowledge base before start...
.\.venv\Scripts\python.exe seed_knowledge.py
echo.
echo  [Local URLs]
echo   - Counter:  http://localhost:10000/counter
echo   - Customer: http://localhost:10000/customer/3
echo   - Waiting:  http://localhost:10000/waiting
echo.
set PORT=10000
set FLASK_DEBUG=1
.venv\Scripts\python.exe app.py
pause
goto MENU

:DOMAIN_RUN
echo [Info] Starting Domain Connection Mode...
call :CHECK_VENV
if errorlevel 1 pause & goto MENU
.venv\Scripts\python.exe run_domain.py
pause
goto MENU

:NORMAL_RUN
echo [Info] Starting Normal Server Mode...
call :CHECK_VENV
if errorlevel 1 pause & goto MENU
echo [Auto-Sync] Updating knowledge base...
.\.venv\Scripts\python.exe seed_knowledge.py
.venv\Scripts\python.exe app.py
pause
goto MENU

:VENV_STATUS
echo ===================================================
echo [MQnet] VENV Status Check ^& Quick Update
echo ===================================================
if not exist .venv (
    echo [!] .venv not found. Redirecting to setup...
    pause
    goto SETUP_VENV
)
echo [OK] .venv found. Checking Libs...
.\.venv\Scripts\python.exe -c "import flask, sqlalchemy, cryptography; print(' - Flask:', flask.__version__); print(' - SQLAlchemy:', sqlalchemy.__version__); print(' - Cryptography: OK')"

if errorlevel 1 goto UPDATE_RELIBS

echo [Info] Updating libraries from requirements.txt (if any)...
.\.venv\Scripts\pip.exe install -r requirements.txt -q
goto VENV_DONE

:UPDATE_RELIBS
echo [!] Some libraries are missing or need update. Running pip install...
.\.venv\Scripts\pip.exe install -r requirements.txt

:VENV_DONE
echo ===================================================
echo [OK] Status check complete.
echo ===================================================
pause
goto MENU

:SETUP_VENV
echo ===================================================
echo [MQnet] VENV Setup and Repair Mode (FORCE RESET)
echo ===================================================
if exist .venv (
    echo [!] WARNING: This will delete the current .venv.
    set /p confirm="Are you sure? (Y/N): "
    if /i not "!confirm!"=="Y" goto MENU
    echo [Info] Removing existing .venv folder...
    rmdir /s /q .venv
)

echo [Info] Checking Python...
set PYTHON_CMD=python
python --version >nul 2>&1
if errorlevel 1 (
    set PYTHON_CMD=py
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python.
        pause
        goto MENU
    )
)

echo [Info] Creating VENV using %PYTHON_CMD%...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 (
    echo [ERROR] Failed to create VENV.
    pause
    goto MENU
)

echo [Info] Configuring Terminal Environment (PowerShell Policy)...
powershell -Command "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force"

echo [Info] Installing packages...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install --no-cache-dir -r requirements.txt

echo ===================================================
echo Setup Complete!
echo ===================================================
pause
goto MENU

:CHECK_VENV
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment is missing or corrupted.
    echo         Please run option 5 or 4 first.
    exit /b 1
)
exit /b 0

:SEED_KNOWLEDGE
echo ===================================================
echo [MQnet] Synchronizing Knowledge DB...
echo ===================================================
call :CHECK_VENV
if errorlevel 1 pause & goto MENU
.\.venv\Scripts\python.exe seed_knowledge.py
echo.
echo [Done] Knowledge base has been updated.
pause
goto MENU
