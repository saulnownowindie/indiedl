"""
Indie Now · NUEVO CORTE — infraestructura compartida
====================================================
Este módulo es EXCLUSIVO de la carpeta "NUEVO CORTE". No importa nada de la
carpeta de subs y no escribe en %LOCALAPPDATA%\\IndieDL\\subs.

Toda la informacion de ejecucion (cache de transcripciones, logs, config de
usuario) vive en %LOCALAPPDATA%\\IndieDL\\cortes, con fallback a las carpetas
locales cache/ y logs/ de esta misma carpeta. Asi los dos sistemas conviven
sin pisarse.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
NOMBRE_APP = "IndieNow-Cortes"
VERSION = "NUEVO CORTE v2.1 · sin lecturas, sin huecos de frames, subs alineados al clip"

# ── Aislamiento respecto de subs ────────────────────────────────────────
BASE_DATOS = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "IndieDL", "cortes",
)
CACHE_DIR = os.path.join(BASE_DATOS, "cache")
LOGS_DIR = os.path.join(BASE_DATOS, "logs")
CONFIG_USUARIO = os.path.join(BASE_DATOS, "config_cortes.json")
CONFIG_PLANTILLA = os.path.join(APP_DIR, "config_cortes.json")

CACHE_LOCAL = os.path.join(APP_DIR, "cache")
LOGS_LOCAL = os.path.join(APP_DIR, "logs")

# Marcadores: customData distinto al de subs ("indienow-verificar").
CUSTOM_MARCA = "indienow-cortes-v1"


def _asegurar(ruta: str, fallback: str) -> str:
    """Crea la carpeta de datos; si no se puede escribir, usa la local."""
    try:
        os.makedirs(ruta, exist_ok=True)
        prueba = os.path.join(ruta, ".escritura_ok")
        with open(prueba, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(prueba)
        return ruta
    except Exception:
        try:
            os.makedirs(fallback, exist_ok=True)
            return fallback
        except Exception:
            return APP_DIR


def iniciar() -> None:
    global CACHE_DIR, LOGS_DIR
    CACHE_DIR = _asegurar(os.path.join(BASE_DATOS, "cache"), CACHE_LOCAL)
    LOGS_DIR = _asegurar(os.path.join(BASE_DATOS, "logs"), LOGS_LOCAL)


iniciar()

# La consola de Windows suele ser cp1252: evitamos que una tilde rara corte
# el proceso. Los archivos de log se escriben siempre en UTF-8.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass


class Log:
    """Log de cada paso, con timestamp y volcado a archivo propio."""

    def __init__(self, nombre: str = "auto_edit"):
        sello = datetime.now().strftime("%Y%m%d")
        self.ruta = os.path.join(LOGS_DIR, f"{nombre}_{sello}.log")
        self._t0 = time.monotonic()
        self.lineas: list[str] = []

    def __call__(self, msg: str) -> None:
        t = time.monotonic() - self._t0
        linea = f"[{datetime.now():%H:%M:%S}] [{t:6.1f}s] {msg}"
        print(linea, flush=True)
        self.lineas.append(linea)
        try:
            with open(self.ruta, "a", encoding="utf-8") as f:
                f.write(linea + "\n")
        except Exception:
            pass

    def paso(self, msg: str) -> None:
        self("")
        self("=== " + msg + " ===")

    def error(self, msg: str, exc: BaseException | None = None) -> None:
        import traceback
        self("ERROR: " + msg)
        if exc is not None:
            for linea in traceback.format_exception(type(exc), exc, exc.__traceback__):
                for sub in linea.rstrip().splitlines():
                    self("   " + sub)


def cargar_config(ruta: str | None = None) -> dict:
    """Config de usuario si existe; si no, la plantilla de esta carpeta."""
    for candidato in (ruta, CONFIG_USUARIO, CONFIG_PLANTILLA):
        if candidato and os.path.isfile(candidato):
            try:
                with open(candidato, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception:
                continue
    return dict(DEFAULTS)


def guardar_config(cfg: dict) -> str:
    try:
        os.makedirs(BASE_DATOS, exist_ok=True)
        with open(CONFIG_USUARIO, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return CONFIG_USUARIO
    except Exception:
        return ""


DEFAULTS = {
    "guion": "",
    "idioma": "es",
    "modelo": "large-v3-turbo",
    "pista_audio": 1,
    "pista_video": 1,
    "copiar_otras_pistas": False,
    "rango": "inout",
    "modo": "ultima",
    "pausa": 0.5,
    "bajada_db": 8.0,
    "usar_cache": True,
    "marcar_ok": False,
    "generar_subtitulos": True,
    "plantilla": "PLANTILLA / inindie now v2",
    "srt_como_pista": False,
    "verificar": True,
    "silencio_min": 0.7,
    "pre": 0.10,
    "post": 0.20,
    "padding_max_antes": 0.30,
    "padding_max_despues": 0.35,
}


# ── Utilidades de texto (copiadas tal cual de la logica de subs) ─────────
def norm(w: str) -> str:
    w = unicodedata.normalize("NFD", str(w).lower())
    return re.sub(r"[^a-z0-9ñ]", "", "".join(c for c in w if unicodedata.category(c) != "Mn"))


def mmss(t: float) -> str:
    t = max(0.0, float(t or 0))
    return f"{int(t // 60)}:{int(t % 60):02d}"


def nombre_seguro(t: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "-", str(t)).strip(" .") or "timeline"


def es_cabecera(l: str) -> bool:
    if l.startswith("=====") or l.startswith("Page"):
        return True
    return ("—" in l or " – " in l) and bool(re.search(r"[“\"‘]|álbum|album|EP", l))


def leer_guion(path: str) -> str:
    if path.lower().endswith(".docx"):
        import docx
        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def palabras_del_guion(texto: str) -> list[tuple[str, str]]:
    """[(normalizada, como_esta_escrita)], sin cabeceras ni titulos en mayusculas.
    Las cabeceras 'Artista — "Cancion"' y los titulos NO se leen en el video."""
    out = []
    for linea in texto.splitlines():
        l = linea.strip()
        if not l or l.isupper() or es_cabecera(l) or l.startswith("AA "):
            continue
        for w in l.split():
            n = norm(w)
            if n:
                out.append((n, w))
    return out


def lineas_del_guion(texto: str) -> list[str]:
    """Lineas leibles del guion (para el reporte de lineas dudosas)."""
    out = []
    for linea in texto.splitlines():
        l = linea.strip()
        if not l or l.isupper() or es_cabecera(l) or l.startswith("AA "):
            continue
        out.append(l)
    return out


def glosario_del_guion(texto: str) -> list[str]:
    """Nombres propios / titulos raros (daneses, griegos, ingleses) para el
    initial_prompt de Whisper. Copiado de subtitulos.py, sin modificarlo."""
    import re as _re
    vistos, out = set(), []
    patron = _re.compile(
        r"(?:[A-ZÁÉÍÓÚÑ][\wáéíóúñ]*|\bII\b)(?:\s+(?:(?:de|la|del|el|y)\s+)*(?:[A-ZÁÉÍÓÚÑ][\wáéíóúñ]*))*"
    )
    for linea in texto.splitlines():
        l = linea.strip()
        if not l or l.isupper() or es_cabecera(l):
            continue
        for m in patron.finditer(l):
            frag = m.group(0).strip(" .,;:¡!¿?«»“”\"")
            ini = m.start()
            previo = l[:ini].rstrip()
            inicio_frase = (not previo) or previo[-1] in ".!?¡¿:«“\""
            if " " not in frag and inicio_frase:
                continue
            if len(frag) < 3 or frag.lower() in vistos:
                continue
            vistos.add(frag.lower())
            out.append(frag)
    return out


def ruta_resolve_api() -> None:
    """Prepara sys.path para importar DaVinciResolveScript desde Python externo."""
    os.environ.setdefault(
        "RESOLVE_SCRIPT_API",
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
    )
    os.environ.setdefault(
        "RESOLVE_SCRIPT_LIB",
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    )
    modulos = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    if modulos not in sys.path:
        sys.path.append(modulos)
