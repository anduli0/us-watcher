@echo off
title US-WATCHER launcher
cd /d "%~dp0"
echo.
echo   ===================================================
echo     US-WATCHER  -  starting API + WEB + WORKER
echo     Public URL: https://krw-watcher.tail3e31a9.ts.net:10000
echo   ===================================================
echo.
start "US-WATCHER API"    "%~dp0_usw-api.bat"
start "US-WATCHER WEB"    "%~dp0_usw-web.bat"
start "US-WATCHER WORKER" "%~dp0_usw-worker.bat"
REM Ensure the Tailscale funnel (idempotent; config also persists in tailscaled).
"C:\Program Files\Tailscale\tailscale.exe" funnel --bg --https=10000 3002 >nul 2>&1
echo   Keep the three windows open to keep the site online.
echo   (You can close THIS launcher window.)
