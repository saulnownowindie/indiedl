# Indie Now DL

Descargador de videos, audios e imágenes para Windows, con vista previa, cola por lotes, historial, selección de fragmento e integración con DaVinci Resolve.

## Instalación con un clic

1. Descarga este repositorio como ZIP y extrae **toda** la carpeta.
2. Haz doble clic en `INSTALAR.bat`.
3. La ventana de PowerShell muestra cada etapa, la salida de `pip` y cualquier error. Si Python 3.12 no está instalado, descarga Python 3.12.10 de python.org y lo instala para el usuario actual.
4. Cuando termine, abre el acceso directo **IndieDL** que se crea en el Escritorio.

El instalador crea un entorno aislado en `%LOCALAPPDATA%\IndieDL\venv`, instala las dependencias, copia la aplicación a `%LOCALAPPDATA%\IndieDL`, crea el acceso directo y registra el protocolo `ytdl://` para los enlaces compatibles. No requiere permisos de administrador. La instalación inicial necesita Internet.

## Qué instala

- Python 3.12 de 64 bits, si hace falta.
- `customtkinter` y Pillow para la interfaz y las vistas previas.
- `yt-dlp` con sus extras para los sitios compatibles.
- `gallery-dl` para imágenes de Instagram.
- `imageio-ffmpeg`, que proporciona FFmpeg cuando no hay una instalación del sistema.

El instalador no incorpora cookies del navegador, historial, configuración personal, videos descargados ni registros. La sesión de Instagram se toma del navegador que el usuario elija en la aplicación. Algunos sitios pueden cambiar sus requisitos de acceso; las cookies y el acceso válido siguen dependiendo de cada cuenta y plataforma.

## Uso

- Pega un enlace y elige video, audio o imágenes.
- Selecciona calidad, carpeta y, si hace falta, un rango para recortar.
- La interfaz muestra el progreso, la velocidad, el tiempo restante y los mensajes.
- `analizar_media.py` permite revisar un archivo de video o audio existente; se puede arrastrar el archivo encima del script o usarlo desde una terminal.

Cuando un archivo requiera normalización a H.264, IndieDL intenta NVIDIA NVENC primero y continúa con codificación por CPU si NVENC o la GPU no están disponibles. La conversión por CPU puede tardar más.

## DaVinci Resolve

La aplicación instala y ejecuta la interfaz de Windows. **No** instala DaVinci Resolve ni cambia sus ajustes. Para importar el archivo descargado, abre Resolve y usa el Media Pool. La conversión opcional de audio a PCM MOV y la normalización de archivos están pensadas para facilitar la compatibilidad, pero no pueden corregir una fuente que ya llegó sin audio.

## Privacidad y permisos

La configuración y el historial se guardan localmente en `%LOCALAPPDATA%\IndieDL\config.json`; el registro se guarda en `%LOCALAPPDATA%\IndieDL\indiedl.log`. Esos archivos quedan fuera del repositorio. Usa la herramienta solamente con contenido que tengas derecho a descargar.

## Desarrollo

Requiere Python 3.12 de 64 bits. Para instalar en un entorno de desarrollo:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app\indiedl.py
```

`yt-dlp` también se actualiza desde la aplicación. Las versiones iniciales de dependencias instaladas en una PC nueva están fijadas en `requirements.txt`.
