"""
Indie Now · NUEVO CORTE — UN SOLO BOTON
=======================================
Flujo completo: transcribir (GPU + cache) -> elegir la ultima toma real ->
cortar -> armar la timeline del reel -> subtitulos -> verificar -> reporte.

Uso:
  auto_edit.bat                          usa el guion de config_cortes.json
  auto_edit.bat "D:\\...\\guion.docx"    usa ese guion (tambien arrastrar y soltar)
  python auto_edit.py --no-gui --guion "..."
  python auto_edit.py --solo-cortes --guion "..."   (saltea subtitulos)

TODO es propio de esta carpeta: config, cache, logs y lanzador viven en
%LOCALAPPDATA%\\IndieDL\\cortes. No toca %LOCALAPPDATA%\\IndieDL\\subs.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback

import indie_common as K


def correr(cfg, log, progreso, reporte):
    """Secuencia completa. Devuelve la lista de lineas del reporte final."""
    import indie_cortes
    import indie_subs
    import indie_verificar

    log(f"{K.VERSION} · {K.NOMBRE_APP}")
    log(f"Datos aislados en: {K.BASE_DATOS}")

    res = indie_cortes.ejecutar(cfg, progreso, log)

    if cfg.get("generar_subtitulos", True):
        log.paso("5 · Subtitulos (estilo de tu script de subs)")
        progreso(92, "Generando subtitulos...")
        try:
            lineas_subs = indie_subs.ejecutar(res, cfg, progreso, log)
            for l in lineas_subs:
                log(l)
            res["rep"] += lineas_subs
        except Exception as exc:
            log.error("Fallo el modulo de subtitulos (el reel ya esta armado)", exc)
            res["rep"].append("Subtitulos: fallo, podes correr tu script de subs aparte.")
    else:
        log("Subtitulos desactivados por config.")

    if cfg.get("verificar", True):
        log.paso("6 · Verificacion y reporte final")
        progreso(99, "Verificando contra el guion...")
        try:
            lineas, dudosas = indie_verificar.ejecutar(res, cfg, log)
            for l in lineas[:6]:
                log(l)
            progreso(100, "Listo")
            return lineas
        except Exception as exc:
            log.error("Fallo la verificacion", exc)
    progreso(100, "Listo")
    return res["rep"]


# ── Interfaz mínima: barra de progreso + reporte ────────────────────────
def gui(cfg, guion_inicial, auto=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("Indie Now · NUEVO CORTE")
    root.geometry("720x620")
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    v_guion = tk.StringVar(value=guion_inicial or cfg.get("guion", ""))
    estado = tk.StringVar(value="EN ESPERA")
    corriendo = {"v": False}

    tk.Label(root, text="INDIE NOW · NUEVO CORTE", font=("Segoe UI", 17, "bold")).pack(
        anchor="w", padx=16, pady=(14, 2))
    tk.Label(root, text="Crudo → timeline del reel ordenada por guion → subtítulos → verificación",
             font=("Segoe UI", 9), fg="#5A6672").pack(anchor="w", padx=16)

    fila = tk.Frame(root)
    fila.pack(fill="x", padx=16, pady=(14, 4))
    tk.Entry(fila, textvariable=v_guion, font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)

    def elegir():
        p = filedialog.askopenfilename(title="Elegí el guion",
                                       filetypes=[("Guion", "*.txt *.docx"), ("Todos", "*.*")])
        if p:
            v_guion.set(p)

    ttk.Button(fila, text="Elegir guion...", command=elegir).pack(side="left", padx=(6, 0))

    barra = ttk.Progressbar(root, maximum=100)
    barra.pack(fill="x", padx=16, pady=(10, 0))
    tk.Label(root, textvariable=estado, font=("Segoe UI", 9), anchor="w").pack(
        fill="x", padx=16, pady=(4, 0))
    caja = tk.Text(root, height=20, wrap="word", font=("Consolas", 9), state="disabled")
    caja.pack(fill="both", expand=True, padx=16, pady=(8, 0))

    boton = ttk.Button(root, text="CORTAR REEL")
    boton.pack(fill="x", padx=16, pady=12)

    def progreso(p, msg):
        def poner():
            barra.configure(value=max(0, min(100, float(p))))
            estado.set(msg)
        root.after(0, poner)

    def reporte(lineas):
        def poner():
            caja.configure(state="normal")
            caja.delete("1.0", "end")
            caja.insert("end", "\n".join(lineas))
            caja.configure(state="disabled")
            caja.see("1.0")
        root.after(0, poner)

    def log_ui(msg):
        def poner():
            caja.configure(state="normal")
            caja.insert("end", msg + "\n")
            caja.configure(state="disabled")
            caja.see("end")
        root.after(0, poner)

    def lanzar():
        if corriendo["v"]:
            return
        guion = v_guion.get().strip().strip('"')
        if not guion or not os.path.isfile(guion):
            messagebox.showwarning("Falta el guion", "Elegí el guion (.txt o .docx) primero.")
            return
        corriendo["v"] = True
        boton.configure(state="disabled", text="TRABAJANDO...")
        cfg2 = dict(cfg)
        cfg2["guion"] = guion
        try:
            K.guardar_config(cfg2)
        except Exception:
            pass

        class LogUI(K.Log):
            def __call__(self, msg):
                super().__call__(msg)
                log_ui(msg.split("] ")[-1] if "] " in msg else msg)

        log = LogUI("auto_edit")

        def trabajo():
            try:
                lineas = correr(cfg2, log, progreso, reporte)
                reporte(lineas)
                estado.set("LISTO")
            except Exception as exc:
                log.error("ERROR GENERAL", exc)
                reporte(["ERROR: " + str(exc), "", "Detalle en el log: " + log.ruta,
                         "", traceback.format_exc()])
                estado.set("ERROR")
            finally:
                corriendo["v"] = False
                root.after(0, lambda: boton.configure(state="normal", text="CORTAR REEL"))

        threading.Thread(target=trabajo, daemon=True).start()

    boton.configure(command=lanzar)
    if auto and guion_inicial and os.path.isfile(guion_inicial):
        root.after(300, lanzar)          # un solo clic en el .bat = arranca solo
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="Indie Now · NUEVO CORTE — flujo completo")
    ap.add_argument("guion_pos", nargs="?", default=None, help="Ruta del guion (arrastrar y soltar)")
    ap.add_argument("--guion", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--solo-cortes", action="store_true")
    ap.add_argument("--auto", action="store_true", help="Arranca sin esperar (lo usa el .bat)")
    args = ap.parse_args()

    cfg = K.cargar_config(args.config)
    for clave, valor in K.DEFAULTS.items():
        cfg.setdefault(clave, valor)
    guion = args.guion or args.guion_pos or cfg.get("guion", "")
    if guion:
        guion = os.path.abspath(guion.strip().strip('"'))
    if args.solo_cortes:
        cfg["generar_subtitulos"] = False
        cfg["verificar"] = False

    if args.no_gui:
        if not guion or not os.path.isfile(guion):
            print("ERROR: pasa --guion con un archivo .txt/.docx valido.", file=sys.stderr)
            return 2
        cfg["guion"] = guion
        log = K.Log("auto_edit")

        def progreso(p, msg):
            print(f"  {float(p):5.1f}%  {msg}", flush=True)

        try:
            lineas = correr(cfg, log, progreso, lambda l: None)
            print("\n" + "\n".join(lineas))
            return 0
        except Exception as exc:
            log.error("ERROR GENERAL", exc)
            print("ERROR: " + str(exc), file=sys.stderr)
            return 1

    gui(cfg, guion, auto=args.auto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
