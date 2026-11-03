# Indie Now DL

Herramientas de escritorio para descargar y preparar material audiovisual de
Indie Now (YouTube, Instagram, TikTok, X/Twitter y Pinterest), más los
utilitarios de cortes para DaVinci Resolve.

> Los subtítulos viven en su propio repo: **https://github.com/saulnownowindie/subs-now**

## Estructura

```
indiedl.py              Punto de entrada de la app de escritorio
indiedl_core.py         Configuración, cookies, descarga y utilidades de media
indiedl_ui.py           Interfaz CustomTkinter (SmoothScroll, App)
launcher.pyw            Lanzador que corrige la etiqueta de integridad de Windows
analizar_media.py       Diagnóstico de un video para DaVinci Resolve
requirements.txt        Dependencias de la app principal
requirements-subs.txt   Dependencias de cortes con Whisper (opcional)

app/                    Copia que usa el instalador como payload
browser-extension/      Extensión de Chrome/Edge (protocolo ytdl://)
installer/instalar.ps1  Instalador (lo invoca INSTALAR.bat)
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

## Cortes

```bat
pip install -r requirements-subs.txt
```

`requirements-subs.txt` instala faster-whisper y las dependencias que usa
`Cortes-Auto/`.

## Subtítulos

La app de subtítulos (Whisper + SRT + traducción) está en
**https://github.com/saulnownowindie/subs-now** y se instala desde ahí:

```powershell
git clone https://github.com/saulnownowindie/subs-now.git
cd subs-now
.\INSTALAR.bat
```

Comparte el mismo entorno virtual (`%LOCALAPPDATA%\IndieDL\venv`), así que no
hace falta duplicar dependencias.

Desde DaVinci Resolve: **Fusion → Scripts → Edit → SubsSaul**.
El lanzador usa `venv\Scripts\pythonw.exe` y deja diagnóstico en
`%LOCALAPPDATA%\IndieDL\subs\lanzador.log`.

## Seguridad

- No subas `config.json`, `youtube_cookies.txt` ni `instagram_cookies.txt`.
- Si una sesión se expuso, cerrala desde el navegador y volvé a iniciar sesión.
- Los cookies se guardan en texto plano en `%LOCALAPPDATA%\IndieDL`; el
  instalador no los copia a ningún lado.
