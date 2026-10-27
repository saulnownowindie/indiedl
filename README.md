# Indie Now DL

Descargador de video, audio e imágenes para Windows, con barra integrada en el navegador.
Interfaz propia (CustomTkinter) con la estética de Indie Now: fondo casi negro, tarjetas
redondeadas y acento amarillo `#FFF333`.

Pensado para trabajar rápido: pegás una URL (o la mandás desde el navegador), elegís
calidad y formato, y el archivo queda donde lo esperás. También maneja recortes por
In/Out, lotes e imágenes de Instagram.

---

## Instalación en un PC nuevo

1. Instalá Git (una sola vez): `winget install --id Git.Git -e`
2. Cloná y ejecutá el instalador:

```powershell
git clone https://github.com/saulnownowindie/indiedl.git
cd indiedl
.\INSTALAR.bat
```

Eso es todo. `INSTALAR.bat` deja el equipo listo sin que tengas que tocar nada más:

| Paso | Qué hace |
|---|---|
| 1 | Verifica Python 3.10–3.13. Si no hay, lo instala solo (winget o el instalador oficial de python.org). |
| 2 | Crea el entorno virtual en `%LOCALAPPDATA%\IndieDL\venv`. |
| 3 | Instala las dependencias de `requirements.txt` (CustomTkinter, Pillow, yt-dlp, gallery-dl, imageio-ffmpeg). |
| 4 | Copia la app y la extensión a `%LOCALAPPDATA%\IndieDL`. |
| 5 | Instala FFmpeg con winget. Si falla, la app usa el binario incluido en `imageio-ffmpeg` y funciona igual. |
| 6 | Registra el protocolo `ytdl://` (lo usa la extensión) y crea accesos directos en Escritorio y Menú Inicio. |

Al terminar abre la app para que veas que quedó andando.

> El instalador se puede correr las veces que quieras: es idempotente. Si actualizás el
> repo con `git pull`, volvé a ejecutar `INSTALAR.bat` y listo.

### Requisitos

- Windows 10 u 11 (64 bits)
- Conexión a internet (solo para instalar y para descargar)
- Opcional: Google Chrome, Edge, Brave o Helium para la barra del navegador

---

## Uso

- **Acceso directo** «Indie Now DL» en el Escritorio o en el Menú Inicio.
- O `Iniciar IndieDL.bat` desde la carpeta del repo.
- Pegá una URL y elegí calidad/formato. Para recortes, completá In/Out.
- Las descargas van a la última carpeta usada (se guarda en la configuración).

### Barra en el navegador (Chrome / Edge / Brave / Helium)

La barra aparece sobre YouTube, Instagram, TikTok, X/Twitter y Pinterest, y manda el
link a la app sin copiar y pegar.

1. Abrí `chrome://extensions` (o `edge://extensions`).
2. Activá **Modo de desarrollador**.
3. **Cargar descomprimida** → elegí `%LOCALAPPDATA%\IndieDL\browser-extension`.
4. Recargá la pestaña donde estés probando.

Los navegadores no permiten que un instalador cargue una extensión en un perfil personal
por su cuenta: ese paso es manual y es una sola vez. El instalador sí deja la carpeta
copiada y el protocolo `ytdl://` registrado, que es lo que la extensión necesita.

---

## Dónde quedan las cosas

| Qué | Dónde |
|---|---|
| Programa | `%LOCALAPPDATA%\IndieDL\` |
| Entorno virtual | `%LOCALAPPDATA%\IndieDL\venv\` |
| Configuración | `%LOCALAPPDATA%\IndieDL\config.json` |
| Registro de errores | `%LOCALAPPDATA%\IndieDL\indiedl.log` |
| Temporales de descarga | `%LOCALAPPDATA%\IndieDL\tmp\` |
| Extensión | `%LOCALAPPDATA%\IndieDL\browser-extension\` |

Ninguno de esos archivos vive en el repo: `config.json`, los logs, los temporales y las
cookies están en `.gitignore`. Podés desinstalar borrando esa carpeta y los accesos
directos.

---

## Actualizar

```powershell
git pull
.\INSTALAR.bat
```

Si cambió la extensión, en `chrome://extensions` tocá **↻ Actualizar** en la tarjeta de
IndieDL y recargá la pestaña.

---

## Estructura

```
indiedl/
├─ app/
│  ├─ indiedl.py            # aplicación (interfaz + descarga)
│  └─ analizar_media.py     # metadatos y duración vía FFmpeg
├─ installer/
│  └─ instalar.ps1          # lógica del instalador
├─ browser-extension/       # extensión de Chrome/Edge (Manifest V3)
│  ├─ manifest.json
│  ├─ content.js
│  ├─ clipboard-hook.js
│  └─ README.md
├─ requirements.txt
├─ INSTALAR.bat             # instalador (doble clic)
└─ Iniciar IndieDL.bat
```

---

## Problemas comunes

**«Falta yt-dlp» o falla la descarga de YouTube**
La app se autoactualiza a la nightly de yt-dlp al arrancar. Si el error sigue, corré:
`%LOCALAPPDATA%\IndieDL\venv\Scripts\python.exe -m pip install -U --pre "yt-dlp[default,curl-cffi]"`

**Instagram pide login**
La app lee las cookies del navegador que elijas en Ajustes. Iniciá sesión en ese navegador,
cerralo (o dejalo abierto si es Firefox/Zen) y reintentá.

**La barra no aparece**
Verificá que la extensión esté cargada y habilitada, y que la página sea uno de los sitios
soportados. Si usabas el userscript de Violentmonkey, desactivalo para que no se dupliquen.

**FFmpeg no aparece**
`winget install --id Gyan.FFmpeg -e`  ·  o reinstalá con `INSTALAR.bat` (la app tiene
fallback propio y funciona sin FFmpeg en el PATH).

---

## Notas

- Probado en Windows 11 con Python 3.12 y `customtkinter` 6.0.
- La interfaz arma la ventana completa antes de mostrarla, así no se ve el armado.
- El scroll de los paneles es propio (rueda suave, 120–190 ms) para que funcione sobre
  cualquier tarjeta o etiqueta, no solo sobre el lienzo.
