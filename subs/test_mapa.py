"""Mapa de escritura: prueba crear un archivo en varias ubicaciones y lista cual funciona."""
import os
import sys
import tkinter as tk
from tkinter import messagebox

home = os.path.expanduser("~")
exe_dir = os.path.dirname(os.path.abspath(sys.executable))

carpetas = [
    ("Carpeta del exe", exe_dir),
    ("Escritorio", os.path.join(home, "Desktop")),
    ("Documentos", os.path.join(home, "Documents")),
    ("Descargas", os.path.join(home, "Downloads")),
    ("LocalAppData", os.environ.get("LOCALAPPDATA", home)),
    ("Temp", os.environ.get("TEMP", home)),
    ("C:\\", "C:\\"),
    ("D:\\ (raiz)", "D:\\"),
    ("D:\\2026", r"D:\2026"),
    ("D:\\...\\axl", r"D:\2026\octubre\30 oct\axl"),
    ("E:\\", "E:\\"),
]

lineas = [f"exe: {sys.executable}", ""]
for nombre, carpeta in carpetas:
    if not os.path.isdir(carpeta):
        lineas.append(f"{nombre}: no existe")
        continue
    ruta = os.path.join(carpeta, "_prueba_indie.tmp")
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("x")
        os.remove(ruta)
        lineas.append(f"{nombre}: OK")
    except Exception as exc:
        lineas.append(f"{nombre}: FALLO ({exc.__class__.__name__} {getattr(exc, 'errno', '')})")

texto = "\n".join(lineas)
try:
    with open(os.path.join(home, "test_mapa_resultado.txt"), "w", encoding="utf-8") as f:
        f.write(texto)
except Exception:
    pass

raiz = tk.Tk()
raiz.withdraw()
messagebox.showinfo("Mapa de escritura", texto)
