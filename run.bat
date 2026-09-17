@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo ERROR: No se encuentra el entorno virtual .venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause