@echo off
setlocal
chcp 65001 >nul
if not exist C:\logs mkdir C:\logs
set LOG=C:\logs\telecloud_copiar_apk.txt
set RAIZ=%~dp0..
set JAVA_HOME=C:\android\jdk17
set ANDROID_HOME=C:\android\sdk
set PATH=%JAVA_HOME%\bin;%ANDROID_HOME%\platform-tools;%PATH%

echo Compilando o app e copiando o arquivo para a pasta Download do celular.
echo Deixe o celular conectado. Isso pode levar alguns minutos.
call :principal > "%LOG%" 2>&1
set RESULTADO=%errorlevel%
type "%LOG%"
echo.
if "%RESULTADO%"=="0" (
  echo === Pronto. No celular, abra o app Arquivos, entre em Download e toque em ===
  echo === telecloud.apk para instalar. ===
) else (
  echo === Deu erro. Veja o texto acima ou o arquivo %LOG% ===
)
pause
exit /b %RESULTADO%

:principal
cd /d "%RAIZ%"
adb devices -l
call gradlew.bat assembleDebug
if errorlevel 1 exit /b 1
adb push app\build\outputs\apk\debug\app-debug.apk /sdcard/Download/telecloud.apk
exit /b %errorlevel%
