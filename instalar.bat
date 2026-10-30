@echo off
REM Prepara o Daily Life na primeira vez: cria o ambiente e instala as bibliotecas.
cd /d "%~dp0"
echo.
echo === Daily Life: instalando ===
where python >nul 2>nul
if errorlevel 1 (
    echo Python nao encontrado. Instale o Python 3.12 em python.org e marque "Add python.exe to PATH".
    pause
    exit /b 1
)
if not exist ".venv" (
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo Algo deu errado na instalacao. Veja a mensagem acima.
    pause
    exit /b 1
)
echo.
set /p EXEMPLOS="Quer criar dados de exemplo para testar? (s/n) "
if /i "%EXEMPLOS%"=="s" python tools\seed.py
echo.
echo Pronto! Abra o Daily Life pelo DailyLife.bat
pause
