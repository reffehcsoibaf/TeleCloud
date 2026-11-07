@echo off
cd /d "%~dp0"
echo Montando o TeleCloud em T: ... feche esta janela (ou Ctrl+C) para encerrar.
"%~dp0venv\Scripts\python.exe" montar.py --unidade T:
echo.
pause
