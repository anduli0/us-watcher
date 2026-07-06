@echo off
title US-WATCHER rebuild web
cd /d "%~dp0apps\web"
echo Rebuilding the web production bundle...
call npm run build
echo Done. Restart the WEB window (or it picks up on next restart) to serve the new build.
pause
