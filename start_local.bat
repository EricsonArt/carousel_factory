@echo off
REM carousel_factory - lokalny tryb (tylko localhost)
cd /d "%~dp0"
streamlit run app.py
pause
