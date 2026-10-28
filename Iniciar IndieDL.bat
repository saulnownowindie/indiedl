@echo off
setlocal
set "APP=%LOCALAPPDATA%\IndieDL"

if not exist "%APP%\venv\Scripts\pythonw.exe" goto :falta
if not exist "%APP%\indiedl.py" goto :falta

rem Si la carpeta volvio a quedar con etiqueta de integridad baja, la corrige.
icacls "%APP%" | findstr /c:"Low Mandatory" >nul && icacls "%APP%" /setintegritylevel "(OI)(CI)M" /T /C /Q >nul

start "" "%APP%\venv\Scripts\pythonw.exe" "%APP%\indiedl.py" %*
exit /b 0

:falta
echo.
echo   Indie Now DL no esta instalado en este equipo.
echo   Ejecuta INSTALAR.bat (una sola vez) y volve a probar.
echo.
pause
exit /b 1
