@echo off
REM Gera dist\DailyLife\DailyLife.exe. Rode depois do instalar.bat.
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
pip install pyinstaller
pyinstaller --noconfirm --windowed --name DailyLife --icon icon.ico ^
  --add-data "dailylife\templates;dailylife\templates" --add-data "dailylife\static;dailylife\static" ^
  --collect-data tzdata --collect-data googleapiclient ^
  --hidden-import win11toast --hidden-import pystray._win32 ^
  main.py
echo.
echo O executavel esta em dist\DailyLife\DailyLife.exe
echo Copie a pasta "data" e o credentials.json para dist\DailyLife se quiser levar seus dados.
pause
