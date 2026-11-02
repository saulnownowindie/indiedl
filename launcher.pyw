"""IndieDL - lanzador.

Lo usan el protocolo ytdl:// y los accesos directos. Se ejecuta con el
pythonw.exe del Python BASE (no el del venv), porque si la carpeta de IndieDL
quedo con etiqueta de integridad BAJA, el pythonw.exe del venv arranca como
proceso de integridad baja y no puede guardar en D:\\, Escritorio, etc.

Hace tres cosas:
  1. Detecta la etiqueta baja por SDDL (";;;LW)"), que no depende del idioma.
  2. Si la ve, la corrige con icacls /setintegritylevel.
  3. Abre indiedl.py con el python del venv, pasandole los argumentos tal cual
     (sin pasar por cmd, asi % y & de la URL no se rompen).
"""
import os
import subprocess
import sys
import tempfile
import time

APP = os.path.dirname(os.path.abspath(__file__))
VENV_PYW = os.path.join(APP, "venv", "Scripts", "pythonw.exe")
VENV_PY = os.path.join(APP, "venv", "Scripts", "python.exe")
MAIN = os.path.join(APP, "indiedl.py")
LOG = os.path.join(APP, "launcher.log")
NO_WINDOW = 0x08000000


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def alert(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "Indie Now DL", 0x10)
    except Exception:
        pass


def _icacls(*args):
    return subprocess.run(["icacls", *args], capture_output=True,
                          creationflags=NO_WINDOW, timeout=60)


def has_low_label(path):
    """True si el objeto tiene etiqueta de integridad baja (SID S-1-16-4096).

    Usa 'icacls /save' y busca ';;;LW)' en el SDDL: es igual en cualquier idioma.
    """
    if not os.path.exists(path):
        return False
    tmp = os.path.join(tempfile.gettempdir(), "indiedl_acl_%d.txt" % os.getpid())
    try:
        _icacls(path, "/save", tmp, "/C", "/Q")
        with open(tmp, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-16", errors="ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") \
            else raw.decode("utf-8", errors="ignore")
        return ";;;LW)" in text
    except Exception as e:
        log("No se pudo leer la etiqueta de %s: %s" % (path, e))
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def self_heal():
    # La carpeta (de ella heredan los archivos nuevos) y el ejecutable del venv.
    if has_low_label(APP) or has_low_label(VENV_PYW):
        log("Etiqueta de integridad baja detectada; corrigiendo.")
        r = _icacls(APP, "/setintegritylevel", "(OI)(CI)M", "/T", "/C", "/Q")
        log("icacls termino con codigo %s" % r.returncode)


def main():
    if not (os.path.isfile(VENV_PYW) and os.path.isfile(MAIN)):
        alert("Indie Now DL no esta instalado en este equipo.\n\n"
              "Ejecuta INSTALAR.bat (una sola vez) y volve a probar.")
        return 1
    try:
        self_heal()
    except Exception as e:
        log("self_heal fallo: %s" % e)
    try:
        subprocess.Popen(
            [VENV_PYW, MAIN, *sys.argv[1:]],
            cwd=APP,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            close_fds=True,
        )
    except Exception as e:
        log("No se pudo abrir IndieDL: %s" % e)
        alert("No se pudo abrir Indie Now DL:\n%s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
