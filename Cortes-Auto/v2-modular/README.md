# Cortes automaticos v2.1 - app modular

Version modular del corte automatico (reemplaza al monolitico
`indienow_cortes_auto.py` de la carpeta anterior, que tenia los 3 fallos del
selector de tomas: agarraba lecturas, ignoraba el orden global y descartaba
tomas dichas a trozos).

- `NUEVO CORTE v2.1 · sin lecturas, sin huecos de frames, subs alineados al clip`:
  - La senal de lectura es el VOLUMEN (se lee ~10-20 dB mas bajo que la voz
    de verdad), no las pausas. Las tomas 100% calladas NO se usan: quedan
    como FALTA (rojo) para arreglar a mano.
  - No corta a mitad de frase: solo separa una toma cuando el hueco es
    silencio real (sin habla).
  - La seleccion de tomas usa programacion dinamica con estado (posicion del
    guion + fin de la ultima toma): orden global garantizado, sin
    superposiciones, y "ultima toma" nunca salta a una frase igual del final.
  - Timeline nueva sin huecos: el video se agrega sin `recordFrame` (Resolve
    lo encadena) y el audio se alinea al inicio real del video.
  - Subtitulos mapeados a las posiciones REALES de los clips y recortados al
    clip donde empiezan: no invaden el clip siguiente. Los titulos entre
    comillas se parten si caen a caballo de dos clips.
  - El SRT queda en el Media Pool y como pista de subtitulos de la timeline
    (`srt_en_timeline`), para compararlo con el SRT hecho a mano.
  - La timeline original queda intacta.
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
