# Extensión IndieDL para Chrome y Edge

La extensión reemplaza el userscript de Violentmonkey. Conserva la barra integrada en las páginas compatibles y envía las acciones a la aplicación IndieDL mediante el protocolo local `ytdl://`. Antes de cambiar, termina o vacía cualquier cola que tengas guardada en Violentmonkey; la nueva extensión mantiene su propia cola.

## Instalar

1. Ejecuta primero `INSTALAR.bat` del repositorio. El instalador copia esta carpeta a `%LOCALAPPDATA%\IndieDL\browser-extension` y registra el protocolo `ytdl://`.
2. Abre `chrome://extensions` en Chrome o `edge://extensions` en Edge.
3. Activa **Modo de desarrollador**.
4. Pulsa **Cargar descomprimida** y selecciona `%LOCALAPPDATA%\IndieDL\browser-extension`.
5. Abre una página compatible. Si Violentmonkey tiene activa la barra IndieDL, desactiva ese userscript para evitar que se duplique.

Los navegadores no permiten que un instalador de escritorio cargue silenciosamente una extensión local en un perfil personal. Este paso manual es una restricción de Chrome/Edge; la extensión y su código quedan incluidos con IndieDL, sin instalar Violentmonkey ni pegar código en un gestor externo.

## Permisos y datos

El manifiesto limita el código a YouTube, Instagram, TikTok, X/Twitter y Pinterest. Usa `storage` para guardar la cola de descargas dentro del almacenamiento de la extensión. No hay servidor de IndieDL ni sincronización en la nube. En TikTok, un pequeño script en el contexto de la página detecta enlaces TikTok que el usuario copia para vincular el botón al video activo.

Para quitarla, abre la página de extensiones del navegador y selecciona **Quitar**. Para actualizarla después de reinstalar IndieDL, usa **Actualizar** en esa página o quítala y cárgala de nuevo desde la carpeta indicada.

