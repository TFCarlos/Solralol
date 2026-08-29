@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Entorno virtual activado: %VIRTUAL_ENV%
cmd /k

#.\.venv\Scripts\Activate.ps1