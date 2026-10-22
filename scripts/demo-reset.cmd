@echo off
REM Double-click to reset the SafePay local demo to fresh seeded data.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo-reset.ps1" %*
pause
