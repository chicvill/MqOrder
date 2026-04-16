@echo off
setlocal
cd /d %~dp0

echo.
echo ================================================
echo   MQnet Quick Setup
echo ================================================

REM -- 1. Copy cloudflared.exe --
echo [1/4] Copying cloudflared.exe...
set CF_SRC=c:\Users\USER\Dev\Ai_order\cloudflared.exe
if exist "%CF_SRC%" (
    copy /y "%CF_SRC%" "%~dp0cloudflared.exe" >nul
    echo   OK: cloudflared.exe copied.
) else (
    echo   SKIP: Not found at %CF_SRC%
)

REM -- 2. Remove old venv --
echo [2/4] Removing old .venv...
if exist .venv (
    rmdir /s /q .venv
    echo   OK: Old .venv removed.
)

REM -- 3. Create new venv --
echo [3/4] Creating new .venv...
set PYTHON_EXE=C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe
if not exist "%PYTHON_EXE%" (
    echo   ERROR: Python not found at %PYTHON_EXE%
    pause
    exit /b 1
)
"%PYTHON_EXE%" -m venv .venv
if errorlevel 1 (
    echo   ERROR: Failed to create venv.
    pause
    exit /b 1
)
echo   OK: .venv created.

REM -- 4. Install packages --
echo [4/4] Installing packages (may take 2-3 min)...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\pip.exe install -r requirements.txt -q

echo.
echo ================================================
echo   Setup complete!
echo.
echo   Local test:    run.bat (select 1)
echo   Domain mode:   .venv\Scripts\python.exe run_domain.py
echo ================================================
echo.
pause
