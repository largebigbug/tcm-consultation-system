@echo off
chcp 936 >nul
set "HERE=%~dp0"
set "BACKEND=%HERE%.."
set "PYTHONIOENCODING=utf-8"
set "LOG=%HERE%..\..\..\serve_demo.log"
cd /d "%BACKEND%"
:: already listening -> nothing to do (idempotent; safe for boot+logon double trigger)
netstat -ano | findstr ":5000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 exit /b 0
"%BACKEND%\.venv\Scripts\python.exe" "%HERE%serve_demo.py" >> "%LOG%" 2>&1