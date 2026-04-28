@echo off
REM carousel_factory - publiczny URL przez Cloudflare Tunnel
REM Wymagania:
REM   1. pip install -r requirements.txt
REM   2. .env z ANTHROPIC_API_KEY, OPENAI_API_KEY, APP_PASSWORD

cd /d "%~dp0"
python scripts\run_public.py
pause
