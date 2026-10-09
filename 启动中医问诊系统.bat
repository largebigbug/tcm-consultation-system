@echo off
chcp 936 >nul
title 中医问诊系统 - 启动
set "CURRENT_DIR=%~dp0"
set "PY=%CURRENT_DIR%code-app\backend\.venv\Scripts\python.exe"
set "BACKEND=%CURRENT_DIR%code-app\backend"
set "LOG=%TEMP%\serve_demo.log"

netstat -ano | findstr ":5000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [OK] 5000 端口已在运行，直接打开页面
    goto :open
)

if not exist "%PY%" (
    echo [ERROR] 未找到后端解释器: %PY%
    pause
    exit /b 1
)

echo [START] 正在启动 中医问诊系统 ...
powershell -NoProfile -Command "Start-Process -FilePath '%PY%' -ArgumentList 'tools\serve_demo.py' -WorkingDirectory '%BACKEND%' -WindowStyle Hidden -RedirectStandardOutput '%LOG%' -RedirectStandardError '%LOG%.err'"

set /a tries=0
:wait
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr ":5000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto :open
set /a tries+=1
if %tries% lss 20 goto :wait
echo [提示] 端口未在 30 秒内就绪，请查看日志: %LOG%
pause
exit /b 1

:open
echo.
echo   本机:   http://localhost:5000
echo   数据库: %BACKEND%\data\app.db
echo   账号:   admin/admin123   yishi^|yaoshi^|daozhen^|keshi^|kufang / 123456
echo   停止:   netstat -ano ^| findstr ":5000 " ^| findstr LISTENING  然后 taskkill /F /PID ^<pid^>
echo.
if not defined HERMES_DEMO_NO_OPEN start http://localhost:5000
timeout /t 3 >nul
exit /b 0