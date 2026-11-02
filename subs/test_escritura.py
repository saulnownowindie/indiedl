"""Prueba 2: separa 'el dialogo se queja' de 'el exe no puede escribir'."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

CARPETA = r"D:\2026\octubre\30 oct\axl"
informe = []


def escribir(ruta, etiqueta):
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("prueba")
        informe.append(f"{etiqueta}: OK -> {ruta}")
        return True
    except Exception as exc:
        informe.append(f"{etiqueta}: FALLO -> {exc!r}")
        return False


raiz = tk.Tk()
raiz.withdraw()

# A) Escritura directa, sin ningun dialogo.
escribir(os.path.join(CARPETA, "prueba_directa.srt"), "A) escritura directa en axl")

# B) Selector de CARPETA (no hace la comprobacion de crear archivo del dialogo de guardar).
elegida = filedialog.askdirectory(parent=raiz, title="Elegí una carpeta", initialdir=CARPETA)
if elegida:
    escribir(os.path.join(elegida, "prueba_carpeta.srt"), "B) selector de carpeta")
else:
    informe.append("B) selector de carpeta: cancelado")

messagebox.showinfo("Resultado", "\n\n".join(informe))
