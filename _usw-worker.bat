@echo off
title US-WATCHER WORKER (APScheduler) - single instance
cd /d "%~dp0"
if not exist "%~dp0.locks" mkdir "%~dp0.locks" 2>nul
REM SINGLE-INSTANCE GUARD: hold an exclusive handle on the lockfile for life.
REM The worker has no port, so a lockfile is its only dedupe; a second copy
REM (e.g. relaunched by the idempotent VBS / health-guard) fails to open the
REM lock and exits, instead of running a duplicate scheduler.
2>nul ( 9>"%~dp0.locks\usw-worker.lock" ( call :run ) ) || (
  echo [usw-worker] another worker supervisor already running - exiting.
  timeout /t 8 /nobreak >nul
  exit /b 0
)
exit /b 0

:run
REM Scheduled news sync + ET briefs + orchestrator + recommendations (reads .env).
:loop
".venv\Scripts\python.exe" apps\worker\main.py
echo.
echo   [WORKER stopped] restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop
