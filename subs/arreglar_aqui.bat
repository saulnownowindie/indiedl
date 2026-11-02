@echo off
setlocal
title IndieNow - corregir permisos y compilar en esta carpeta

:: ============================================================
:: Corrige la etiqueta de integridad BAJA de esta carpeta (la que
:: impide que el .exe escriba en cualquier lado), borra build/dist
:: viejos, recompila y verifica el resultado. No mueve nada.
:: Ponelo en la carpeta del proyecto (donde esta subtitulos.py).
:: ============================================================
cd /d "%~dp0"

if not exist "subtitulos.py" (
    echo ERROR: no encuentro subtitulos.py en %CD%
    echo Pone este .bat en la carpeta del proyecto y volve a ejecutarlo.
    pause
    exit /b 1
)

echo.
echo Carpeta: %CD%
echo.
echo Etiqueta ANTES de corregir:
icacls "%CD%" | find /I "Mandatory Label"
echo.

echo [1/4] Cerrando programas de prueba si estan abiertos...
taskkill /F /IM IndieNow-Subtitulos.exe >nul 2>&1
taskkill /F /IM test_mapa.exe >nul 2>&1
taskkill /F /IM test_guardar.exe >nul 2>&1
taskkill /F /IM test_escritura.exe >nul 2>&1

echo [2/4] Poniendo integridad NORMAL (Medium) en toda la carpeta...
icacls "%CD%" /setintegritylevel "(OI)(CI)M" /T /C >nul
echo Etiqueta DESPUES de corregir:
icacls "%CD%" | find /I "Mandatory Label"

echo.
echo [3/4] Borrando build y dist viejos y compilando...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
call compilar.bat

echo.
echo [4/4] Verificando el ejecutable...
set "EXE=%CD%\dist\IndieNow-Subtitulos\IndieNow-Subtitulos.exe"
if not exist "%EXE%" (
    echo ERROR: no se genero %EXE%
    echo Mira los mensajes de la compilacion arriba.
    pause
    exit /b 1
)

icacls "%EXE%" | find /I "Low Mandatory" >nul
if not errorlevel 1 (
    echo.
    echo AVISO: el .exe SIGUE con etiqueta baja.
    echo Pasame la salida de: icacls "%CD%"
) else (
    echo.
    echo OK: el .exe tiene integridad normal. Ya podes guardar donde quieras.
)

echo.
echo Ejecutable: %EXE%
start "" explorer "%CD%\dist\IndieNow-Subtitulos"
pause
endlocal
