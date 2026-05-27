@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\Create-Luna-Website-Shortcut.ps1"
pause
