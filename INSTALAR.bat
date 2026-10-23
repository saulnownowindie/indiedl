@echo off
setlocal
title IndieDL - Instalador
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\setup_windows.ps1"
if errorlevel 1 (
  echo.
  echo La instalacion termino con errores. Copia el mensaje de arriba para revisarlo.
  pause
)
endlocal
