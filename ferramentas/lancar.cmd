@echo off
setlocal
chcp 65001 >nul
if not exist C:\logs mkdir C:\logs
set LOG=C:\logs\telecloud_lancar.txt
set JAVA_HOME=C:\android\jdk17
set ANDROID_HOME=C:\android\sdk
cd /d "%~dp0.."
echo Lancando o TeleCloud. Isto compila o .exe e o .apk e pode levar varios minutos.
echo Sem o argumento --publicar nada e enviado ao GitHub. Para publicar: ferramentas\lancar.cmd --publicar
"venv\Scripts\python.exe" -I ferramentas\lancar.py %* > "%LOG%" 2>&1
set RESULTADO=%errorlevel%
type "%LOG%"
echo.
if "%RESULTADO%"=="0" (echo === Pronto. ===) else (echo === Deu erro. Veja o texto acima ou o arquivo %LOG% ===)
pause
exit /b %RESULTADO%
