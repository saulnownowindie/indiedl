"""
Indie Now · NUEVO CORTE — verificacion y reporte final
======================================================
Usa una COPIA local de verificacion.py (_base/verificacion_base.py, y la
copia de trabajo verificacion.py de ESTA carpeta) en modo SOLO LECTURA:
se llama unicamente a alinear(), sin agregar marcadores propios, para no
pisar los marcadores del sistema de subs (customData distinto).

P6: reporte final
  · "X de Y palabras del guion estan, en orden"
  · lista de lineas dudosas con su MINUTO EN LA TIMELINE DEL REEL
  · log de cada paso y de cada error
"""
from __future__ import annotations

import importlib.util
import os
from datetime import datetime

import indie_common as K
import indie_subs


def _alinear_local():
    """Carga verificacion.py de ESTA carpeta por ruta absoluta (aislamiento)."""
    ruta = os.path.join(K.APP_DIR, "verificacion.py")
    spec = importlib.util.spec_from_file_location("verificacion_cortes", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.alinear


def ejecutar(resultado, cfg, log):
    alinear = _alinear_local()
    guion = indie_subs.tokenizar_guion(resultado["texto_guion"])
    pal = [(w, a, b) for w, a, b, _ in resultado["palabras_nueva"]]
    ev, ok, total = alinear(pal, guion)

    pct = 100.0 * ok / total if total else 0.0
    titular = f"{ok} de {total} palabras del guion estan, en orden ({pct:.0f} %)."
    log(titular)

    dudosas = []
    for d in resultado["lineas_dudosas"]:
        dudosas.append(f"{d['minuto']:>7}  {d['color']:7} {d['nombre']}: {d['nota']}")
    # eventos de la alineacion (sobras / faltas medidas en la timeline nueva)
    for e in ev:
        dudosas.append(f"{K.mmss(e['t']):>7}  {e['color']:7} {e['nombre']}: "
                       f"{e['nota'].splitlines()[0]}")
    dudosas.sort(key=lambda x: x[:7].strip())

    lineas = [
        K.VERSION,
        titular,
        f"Timeline: {resultado['nueva'].GetName()}  ·  {resultado['total_cortes']} cortes  ·  "
        f"{K.mmss(resultado['dur_final'])} de {K.mmss(resultado['dur_total'])} originales.",
        f"Lineas para revisar a mano: {len(dudosas)}",
    ]
    for r in resultado["rep"][2:]:
        lineas.append(r)

    # Reporte en archivo propio
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    ruta = os.path.join(K.LOGS_DIR, f"{K.nombre_seguro(resultado['tl_name'])}_{sello}_reporte.txt")
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n\n=== LINEAS DUDOSAS (minuto en la timeline del reel) ===\n")
            f.write("\n".join(dudosas) if dudosas else "  (ninguna)")
            f.write("\n\n=== LECTURAS / ARRANQUES EN FALSO DESCARTADOS ===\n")
            for t, txt, razon in resultado["lecturas"]:
                f.write(f"{K.mmss(t):>7}  {txt}  [{razon}]\n")
            f.write("\n\n=== LOG COMPLETO ===\n")
            f.write("\n".join(log.lineas))
        lineas.append("Reporte guardado: " + ruta)
    except Exception as exc:
        lineas.append("No pude guardar el reporte: " + str(exc))

    if dudosas:
        lineas.append("")
        lineas.append("=== LINEAS DUDOSAS (minuto en la timeline del reel) ===")
        lineas.extend(dudosas[:40])
        if len(dudosas) > 40:
            lineas.append(f"... y {len(dudosas) - 40} mas (en el reporte).")

    return lineas, dudosas
