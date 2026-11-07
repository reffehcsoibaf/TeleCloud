@echo off
cd /d "%~dp0"
start "" "%~dp0venv\Scripts\pythonw.exe" montar.py --unidade T:
