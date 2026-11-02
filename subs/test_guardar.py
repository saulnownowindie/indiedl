"""Prueba mínima: abre el diálogo de guardar y muestra qué devuelve.
Sirve para saber si el problema es de PyInstaller o de la app."""
import tkinter as tk
from tkinter import filedialog, messagebox

raiz = tk.Tk()
raiz.withdraw()
ruta = filedialog.asksaveasfilename(
    parent=raiz,
    title="Prueba de guardado",
    initialdir=r"D:\2026\octubre\30 oct\axl",
    initialfile="Axl Rose.srt",
    defaultextension=".srt",
    filetypes=[("SRT", "*.srt")],
)
if ruta:
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("prueba")
        messagebox.showinfo("Resultado", f"OK, guardó:\n{ruta}")
    except Exception as exc:
        messagebox.showerror("Resultado", f"El diálogo aceptó pero al escribir falló:\n{exc!r}")
else:
    messagebox.showinfo("Resultado", "Cancelado (no eligió ruta).")
