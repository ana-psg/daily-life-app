@echo off
REM Mostra o que carrega e o que o Windows bloqueou. Resultado em data\diagnostico.txt
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" tools\diagnostico.py
) else (
    python tools\diagnostico.py
)
echo.
pause
