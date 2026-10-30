@echo off
REM Abre o Daily Life sem janela de terminal.
REM Na primeira vez, rode antes o instalar.bat
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    REM Instala bibliotecas novas que uma atualização do app possa ter trazido
    ".venv\Scripts\python.exe" -c "import importlib.util as u, sys; sys.exit(not all(u.find_spec(m) for m in ('dateutil', 'flask', 'cryptography')))" 2>nul || ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
    start "" ".venv\Scripts\pythonw.exe" main.py
) else (
    start "" pythonw main.py
)
