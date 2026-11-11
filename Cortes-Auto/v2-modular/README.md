# Cortes automaticos v2 - app modular

Version modular del corte automatico (reemplaza al monolitico
`indienow_cortes_auto.py` de la carpeta anterior, que tenia los 3 fallos del
selector de tomas: agarraba lecturas, ignoraba el orden global y descartaba
tomas dichas a trozos).

- `NUEVO CORTE v2 · volumen por piezas + orden global (DP)`:
  - La senal de lectura es el VOLUMEN (se lee ~10-20 dB mas bajo que la voz
    de verdad), no las pausas.
  - La seleccion de tomas usa programacion dinamica con estado (posicion del
    guion + fin de la ultima toma): orden global garantizado, sin
    superposiciones, y "ultima toma" nunca salta a una frase igual del final.
  - Motor de transcripcion: faster-whisper (no se cambia).

## Correr
- `auto_edit.bat` (GUI con pythonw del venv)
- `auto_edit_debug.bat` (consola con logs)

## Dependencias
- ffmpeg en PATH
- `pip install faster-whisper python-docx numpy`
- (opcional) `gpu_runtime.py` junto a estos archivos prepara CUDA

## Estructura
- `auto_edit.py`      GUI / orquestador
- `indie_cortes.py`   transcripcion + seleccion de tomas + timeline nueva
- `indie_subs.py`     subtitulos (bloques por palabra, titulos entre comillas
  como un solo bloque, SRT con `<b>`)
- `indie_common.py`   constantes compartidas + VERSION
- `config_cortes.json` configuracion (pausa, bajada_db, pre/post, modo)
- `mezcla_audio.py`, `verificacion.py`, `indie_verificar.py` utilidades
