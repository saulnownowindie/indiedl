@echo off
echo Iniciando compilacion de IndieNow...
call venv\Scripts\activate 2>nul || echo (Usando Python global)

:: Instalar dependencias necesarias si faltan
pip install pyinstaller faster-whisper python-docx numpy Pillow

:: Borrar builds anteriores
rmdir /s /q build
rmdir /s /q dist

:: Compilar con las banderas correctas para Tkinter, CUDA y Whisper
pyinstaller --noconfirm --onedir --windowed ^
  --name "IndieNow-Subtitulos" ^
  --manifest app.manifest ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all av ^
  --collect-all tokenizers ^
  --hidden-import "tkinter" ^
  --hidden-import "PIL" ^
  --hidden-import "numpy" ^
  subtitulos.py

echo.
echo Compilacion terminada. El ejecutable esta en la carpeta "dist/IndieNow-Subtitulos/".
pause