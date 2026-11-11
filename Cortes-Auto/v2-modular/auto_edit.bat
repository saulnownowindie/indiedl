@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  Indie Now - NUEVO CORTE - UN SOLO BOTON
rem  Doble clic .............. usa el guion de config_cortes.json
rem  Arrastra el guion aca ... usa ese .txt / .docx
rem  NO toca la instalacion de subs (%LOCALAPPDATA%\IndieDL\subs)
rem ============================================================
set "APP=%~dp0"
set "GUION=%~1"
set "DATOS=%LOCALAPPDATA%\IndieDL\cortes"
if not exist "%DATOS%\logs" mkdir "%DATOS%\logs" 2>nul

set "PYW="
if exist "%LOCALAPPDATA%\IndieDL\venv\Scripts\pythonw.exe" set "PYW=%LOCALAPPDATA%\IndieDL\venv\Scripts\pythonw.exe"
rem  No se usa nada de %LOCALAPPDATA%\IndieDL\subs (aislamiento total).
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
if not defined PYW set "PYW=pythonw.exe"

echo %DATE% %TIME% Lanzando: %PYW%  guion="%GUION%" >> "%DATOS%\logs\lanzador.log"
start "" "%PYW%" "%APP%auto_edit.py" --auto "%GUION%"
endlocal
