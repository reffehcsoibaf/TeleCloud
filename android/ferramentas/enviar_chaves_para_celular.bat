@echo off
setlocal
chcp 65001 >nul
if not exist C:\logs mkdir C:\logs
set LOG=C:\logs\telecloud_enviar_chaves.txt
set RAIZ=%~dp0..\..
set ANDROID_HOME=C:\android\sdk
set PATH=%ANDROID_HOME%\platform-tools;%PATH%
rem Origem das chaves: o config.json do TeleCloud instalado; ou o da pasta dados do projeto; ou o caminho passado como argumento.
set ORIGEM=%APPDATA%\TeleCloud\config.json
if not exist "%ORIGEM%" set ORIGEM=%RAIZ%\dados\config.json
if not "%~1"=="" set ORIGEM=%~1
set TEMPDIR=%~dp0tmp
set ARQUIVO=%TEMPDIR%\telecloud-config.json
set PY=%RAIZ%\venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo Enviando as chaves do Telegram para o celular. Deixe o celular conectado.
call :principal > "%LOG%" 2>&1
set RESULTADO=%errorlevel%
if exist "%ARQUIVO%" del "%ARQUIVO%"
type "%LOG%"
echo.
if "%RESULTADO%"=="0" (
  echo === Pronto. No celular, abra o app TeleCloud e toque em "Importar o arquivo de chaves". ===
  echo === O arquivo se chama telecloud-config.json, na pasta Download. O app o apaga depois de importar. ===
) else (
  echo === Deu erro. Veja o texto acima ou o arquivo %LOG% ===
)
pause
exit /b %RESULTADO%

:principal
echo Origem: %ORIGEM%
if not exist "%ORIGEM%" (
  echo ERRO: nao encontrei o config.json do TeleCloud. Abra o TeleCloud do Windows e entre na conta ao menos uma vez.
  exit /b 1
)
if not exist "%TEMPDIR%" mkdir "%TEMPDIR%"
"%PY%" -I "%~dp0exportar_chaves.py" "%ORIGEM%" "%ARQUIVO%"
if errorlevel 1 exit /b 1
adb devices -l
adb push "%ARQUIVO%" /sdcard/Download/telecloud-config.json
if errorlevel 1 exit /b 1
rem Faz o Android indexar o arquivo, para ele aparecer no seletor de arquivos.
adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Download/telecloud-config.json
exit /b 0
