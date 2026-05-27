@echo off
title Luna Website
cd /d "%~dp0"
REM Marketing site (port 5180). Canned chat works without the bot.
python main.py --website --no-bot
if errorlevel 1 (
  echo.
  echo Failed to start. Try: cd website ^&^& npm install ^&^& npm run dev
  pause
)
