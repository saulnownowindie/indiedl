# Indie Now DL

Herramientas de escritorio para descargar y preparar material audiovisual de
Indie Now (YouTube, Instagram, TikTok, X/Twitter y Pinterest), más los
utilitarios de subtítulos y cortes para DaVinci Resolve.

## Estructura

```
indiedl.py              Punto de entrada de la app de escritorio
indiedl_core.py         Configuración, cookies, descarga y utilidades de media
indiedl_ui.py           Interfaz CustomTkinter (SmoothScroll, App)
launcher.pyw            Lanzador que corrige la etiqueta de integridad de Windows
analizar_media.py       Diagnóstico de un video para DaVinci Resolve
requirements.txt        Dependencias de la app principal
requirements-subs.txt   Dependencias de subtítulos/cortes (opcional)

app/                    Copia que usa el instalador como payload
browser-extension/      Extensión de Chrome/Edge (protocolo ytdl://)
installer/instalar.ps1  Instalador (lo invoca INSTALAR.bat)
subs/                   App IndieNow-Subtitulos (Whisper + SRT)
Cortes-Auto/            Automatización de cortes en DaVinci Resolve
docs/                   Documentación editorial
```

`venv/`, `tmp/`, `cache/`, `config.json`, los `*.log` y los cookies están
ignorados por Git y no deben versionarse.

## Uso rápido

```bat
INSTALAR.bat
```

El instalador crea `%LOCALAPPDATA%\IndieDL\venv`, instala `requirements.txt`,
registra el protocolo `ytdl://` y copia la app y la extensión.

Para ejecutar sin instalar:

```bat
venv\Scripts\pythonw.exe indiedl.py
```

## Subtítulos y cortes

```bat
pip install -r requirements-subs.txt
cd subs
venv\Scripts\python.exe subtitulos.py
```

## Seguridad

- No subas `config.json`, `youtube_cookies.txt` ni `instagram_cookies.txt`.
- Si una sesión se expuso, cerrala desde el navegador y volvé a iniciar sesión.
- Los cookies se guardan en texto plano en `%LOCALAPPDATA%\IndieDL`; el
  instalador no los copia a ningún lado.
