@echo off
chcp 936 >nul
title 配置 DeepSeek 密钥 - 中医问诊系统
set "HERE=%~dp0"
set "ENV=%HERE%code-app\backend\.env"
set "PY=%HERE%code-app\backend\.venv\Scripts\python.exe"

echo ============================================================
echo   配置 DEEPSEEK_API_KEY（写入 code-app\backend\.env）
echo ------------------------------------------------------------
echo   密钥不会显示在屏幕上，也不会写进任何聊天/日志
echo   直接回车 = 取消
echo ============================================================
echo.
set "KEY="
set /p "KEY=请粘贴 DeepSeek API Key 后回车: "
if not defined KEY (echo [取消] 未输入任何内容。& pause & exit /b 0)

echo %KEY%| findstr /b /c:"sk-" >nul
if errorlevel 1 (echo [ERROR] 看起来不是 DeepSeek 密钥（应以 sk- 开头）。& set "KEY="& pause& exit /b 1)

if not exist "%HERE%code-app\backend" (echo [ERROR] 未找到后端目录: %HERE%code-app\backend & set "KEY=" & pause & exit /b 1)
if exist "%ENV%" (
    findstr /v /b /c:"DEEPSEEK_API_KEY=" "%ENV%" > "%ENV%.tmp"
) else (
    type nul > "%ENV%.tmp"
)
>> "%ENV%.tmp" echo DEEPSEEK_API_KEY=%KEY%
>> "%ENV%.tmp" echo AI_PROVIDER=deepseek
move /y "%ENV%.tmp" "%ENV%" >nul
set "KEY="
findstr /b /c:"DEEPSEEK_API_KEY=sk-" "%ENV%" >nul
if errorlevel 1 (echo [ERROR] 写入失败，请检查目录权限: %ENV% & pause & exit /b 1)
echo [OK] 已写入 %ENV%（仅显示是否成功，不回显密钥）

echo [..] 重启演示服务以载入新凭据
schtasks /end /tn "Hermes_Demo_Zhongyi_5000" >nul 2>&1
ping -n 3 127.0.0.1 >nul
schtasks /run /tn "Hermes_Demo_Zhongyi_5000" >nul 2>&1
set /a t=0
:wait
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr ":5000 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto :check
set /a t+=1
if %t% lss 20 goto :wait
echo [提示] 端口 5000 未就绪，请查看 serve_demo.log
pause
exit /b 1

:check
echo.
"%PY%" "%HERE%code-app\backend\tools\check_ai_live.py"
echo.
echo 完成。若上面显示 已真实联通，刷新网页后右侧 AI 区即可对话。
pause