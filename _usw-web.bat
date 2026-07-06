@echo off
title US-WATCHER WEB (next start :3002) - single instance, health-aware
cd /d "%~dp0apps\web"
REM Serves the production build; Next proxies /api -> 127.0.0.1:8088 (same origin).
REM
REM SINGLE-INSTANCE BY DESIGN: if something already listens on 3002, stand by
REM instead of killing it -- prevents two supervisors thrashing the port.
:loop
powershell -NoProfile -Command "try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',3002); $c.Close(); exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  timeout /t 20 /nobreak >nul
  goto loop
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3002" ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
call npx next start -p 3002
echo.
echo   [WEB stopped] restarting in 3s...  (close this window to take the site offline)
timeout /t 3 /nobreak >nul
goto loop
