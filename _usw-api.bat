@echo off
title US-WATCHER API (127.0.0.1:8088) - single instance, health-aware
cd /d "%~dp0"
REM Reads .env from this directory (AGENT_RUNTIME=llm, ANTHROPIC_API_KEY, secrets).
REM
REM SINGLE-INSTANCE BY DESIGN: before reclaiming the port, probe /health. If a
REM HEALTHY API already answers on 8088, back off instead of killing it. This turns
REM a second supervisor into a passive stand-by (graceful failover) rather than a
REM rival that taskkills the live listener -- which eliminates the port-thrash that
REM caused intermittent "API connection failed".
:loop
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 'http://127.0.0.1:8088/health'; if ([int]$r.StatusCode -ge 200 -and [int]$r.StatusCode -lt 300) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
  REM A healthy API is already serving -- stand by; do NOT reclaim or restart.
  timeout /t 20 /nobreak >nul
  goto loop
)
REM No healthy API -> reclaim any stale/orphan listener, then start uvicorn.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8088" ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
".venv\Scripts\python.exe" -m uvicorn main:app --app-dir apps/api --host 127.0.0.1 --port 8088 --no-use-colors
echo.
echo   [API stopped] restarting in 3s...  (close this window to take the API offline)
timeout /t 3 /nobreak >nul
goto loop
