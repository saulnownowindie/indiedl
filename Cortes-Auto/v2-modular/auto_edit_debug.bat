@echo off
chcp 65001 >nul
setlocal
rem Igual que auto_edit.bat pero con consola visible: sirve para ver errores.
set "APP=%~dp0"
set "GUION=%~1"
set "PY="
if exist "%LOCALAPPDATA%\IndieDL\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\IndieDL\venv\Scripts\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY set "PY=python"
"%PY%" "%APP%auto_edit.py" --auto "%GUION%"
echo.
echo Si ves un error arriba, esta consola te muestra el detalle.
pause
endlocal
