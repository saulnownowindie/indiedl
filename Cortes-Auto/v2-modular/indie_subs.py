"""
Indie Now · NUEVO CORTE — subtitulos del reel
=============================================
Copia ADAPTADA (solo lectura) de las funciones de subtitulos.py:
  tokenizar_guion / _extender_grupos / limpiar_puntuacion_final /
  _envolver_comillas / armar_bloques / tc / aplicar_plantilla.

NO importa ni modifica subtitulos.py, subtitulos_ui.py ni indie_ui.py.
El estilo se conserva EXACTO:
  · una palabra por subtitulo
  · nombres de canciones / albumes / artistas en UN SOLO bloque entre comillas
  · duracion maxima 0.6 s + factor por largo, sin solapes

Novedad: los tiempos vienen de la transcripcion ORIGINAL ya mapeados a la
timeline NUEVA por indie_cortes._mapear_tiempo, asi que NO se re-transcribe
(rapido) y los subtitulos quedan pegados a las palabras cortadas.
"""
from __future__ import annotations

import difflib
import math
import os
import time

import indie_common as K

_COMILLAS_PARES = {"“": "”", "‘": "’", '"': '"', "'": "'", "«": "»", "‹": "›"}
_PUNT_FINAL = ",.;:!?…"
_NOMBRES_CON_TEXTO = ("text", "title", "titulo", "título", "caption", "subtitle")
_TIPOS_CON_TEXTO = ("fusion title", "text+", "text plus", "title")
_TIPOS_NO_TEXTO = ("adjustment", "audio", "still", "video", "compound", "timeline",
                   "color bars", "noise", "blank", "transparent", "matte")
_NOMBRES_NO_TEXTO = ("adjustment", "layer", "light", "zoom", "blur", "matte")
_LOTE_INSERCION = 4


# ── Estilo: agrupacion de nombres entre comillas ────────────────────────
def tokenizar_guion(texto: str):
    """Copia literal de subtitulos.py: las secuencias entre comillas del guion
    forman un unico grupo (un solo bloque de subtitulo)."""
    toks, g = [], 0
    for linea in texto.splitlines():
        l = linea.strip()
        if not l or l.isupper() or K.es_cabecera(l) or l.startswith("AA "):
            continue
        for m in __import__("re").finditer(r"[«“\"](.+?)[»”\"]|(\S+)", l):
            if m.group(1):
                g += 1
                for w in m.group(1).split():
                    w = w.strip(".,;:¡¿()")
                    if w:
                        toks.append((w, g))
            else:
                w = m.group(2).strip(".,;:¡!¿?()“”«»\"")
                if w:
                    toks.append((w, None))
    return _extender_grupos(toks)


def _extender_grupos(toks):
    """Copia literal: extiende los grupos entre comillas a las apariciones
    iguales SIN comillas en el resto del guion."""
    grupos = {}
    for w, g in toks:
        if g is not None:
            grupos.setdefault(g, []).append(w)
    if not grupos:
        return toks
    cands = {}
    for ws in grupos.values():
        cands[(tuple(ws), len(ws) < 3)] = ws
        if len(ws) > 3:
            for L in range(len(ws) - 1, 2, -1):
                for k in range(len(ws) - L + 1):
                    cands[(tuple(ws[k:k + L]), False)] = ws[k:k + L]
    orden = sorted(cands.items(), key=lambda kv: -len(kv[1]))
    out = [list(t) for t in toks]
    nuevo = max(grupos) + 1
    for (_, exacto), ws in orden:
        L = len(ws)
        clave = tuple(ws) if exacto else tuple(K.norm(x) for x in ws)
        i = 0
        while i + L <= len(out):
            ven = out[i:i + L]
            if all(v[1] is None for v in ven):
                cand = tuple(v[0] for v in ven) if exacto else tuple(K.norm(v[0]) for v in ven)
                if cand == clave:
                    for v in ven:
                        v[1] = nuevo
                    nuevo += 1
                    i += L
                    continue
            i += 1
    return [(w, g) for w, g in out]


def limpiar_puntuacion_final(t):
    if not t:
        return t
    abre, cierra = None, None
    if len(t) >= 2 and t[0] in _COMILLAS_PARES and t[-1] == _COMILLAS_PARES[t[0]]:
        abre, cierra = t[0], t[-1]
        t = t[1:-1]
    t = t.rstrip(_PUNT_FINAL)
    if abre is not None:
        t = abre + t + cierra
    return t


def _envolver_comillas(texto):
    if len(texto) >= 2 and texto[0] in _COMILLAS_PARES and texto[-1] == _COMILLAS_PARES[texto[0]]:
        return "“" + texto[1:-1] + "”"
    return "“" + texto + "”"


def armar_bloques(palabras):
    """Copia literal de subtitulos.py. `palabras` = [texto, inicio, fin, grupo]."""
    normalizadas = []
    ultimo_fin = 0.0
    for palabra in palabras:
        if len(palabra) < 4:
            continue
        texto, inicio, fin, grupo = palabra[:4]
        try:
            inicio = max(0.0, float(inicio))
            fin = max(inicio, float(fin))
        except (TypeError, ValueError):
            continue
        inicio = max(inicio, ultimo_fin)
        fin = max(fin, inicio)
        normalizadas.append([texto, inicio, fin, grupo])
        ultimo_fin = fin
    palabras = normalizadas
    bl = []
    i = 0
    while i < len(palabras):
        t, s, e, g = palabras[i]
        if g is not None:
            j = i
            while j + 1 < len(palabras) and palabras[j + 1][3] == g:
                j += 1
            partes = [limpiar_puntuacion_final(x[0]) for x in palabras[i:j + 1]]
            texto = " ".join(partes).strip()
            texto = _envolver_comillas(texto)
            bl.append([texto, s, palabras[j][2]])
            i = j + 1
        else:
            bl.append([limpiar_puntuacion_final(t), s, e])
            i += 1
    for b in bl:
        es_nombre = b[0].startswith("“")
        factor = 0.15 if es_nombre else 0.08
        b[2] = min(b[2], b[1] + 0.6 + factor * len(b[0]))
    for k in range(len(bl) - 1):
        if 0 <= bl[k + 1][1] - bl[k][2] < 0.35:
            bl[k][2] = bl[k + 1][1]
    for b in bl:
        b[2] = max(b[2], b[1] + 0.08)
    for k in range(len(bl) - 1):
        if bl[k + 1][1] < bl[k][2]:
            bl[k + 1][1] = bl[k][2]
            bl[k + 1][2] = max(bl[k + 1][2], bl[k + 1][1] + 0.08)
    return bl


def tc(t):
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def escribir_srt(bloques, ruta):
    partes = []
    for i, (texto, s, e) in enumerate(bloques, 1):
        # <b> como en los SRT hechos a mano (Respect/estilos del editor)
        partes.append(f"{i}\n{tc(s)} --> {tc(e)}\n<b>{texto}</b>\n\n")
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("".join(partes))
    return ruta


# ── Grupos: indice de palabra del guion -> id de bloque entre comillas ───
def grupos_del_guion(texto, G):
    """Devuelve (grupos, limpios) alineados a los indices de G.

    `grupos[i]`  = id del bloque entre comillas (o None = palabra suelta).
    `limpios[i]` = palabra del guion SIN la puntuacion de los bordes, tal
                   como la usa subtitulos.py. Esto es lo que evita que un
                   titulo quede como “Am I Offending You?” en vez de
                   “Am I Offending You”.
    """
    toks = tokenizar_guion(texto)
    tn = [K.norm(w) for w, _ in toks]
    gn = [w for w, _ in G]
    grupos = [None] * len(G)
    limpios = [d for _, d in G]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, gn, tn, autojunk=False).get_opcodes():
        if tag == "equal":
            for d in range(i2 - i1):
                if i1 + d < len(grupos):
                    grupos[i1 + d] = toks[j1 + d][1]
                    limpios[i1 + d] = toks[j1 + d][0]
        elif tag == "replace":
            # nombres raros mal oidos: reparte por similitud
            usados = set()
            for a in range(i1, i2):
                mejor, best = None, 0.0
                for b in range(j1, j2):
                    if b in usados:
                        continue
                    r = difflib.SequenceMatcher(None, gn[a], tn[b]).ratio()
                    if r > best:
                        mejor, best = b, r
                if mejor is not None and best >= 0.7 and a < len(grupos):
                    grupos[a] = toks[mejor][1]
                    limpios[a] = toks[mejor][0]
                    usados.add(mejor)
    return grupos, limpios


# ── Plantillas Text+ en el Media Pool ───────────────────────────────────
def _props_clip(c):
    try:
        return {str(k).lower(): str(v) for k, v in (c.GetClipProperty() or {}).items()}
    except Exception:
        try:
            return {"type": str(c.GetClipProperty("Type") or "")}
        except Exception:
            return {}


def _tiene_textplus(clip):
    try:
        comp = clip.GetFusionCompByIndex(1)
        return bool(comp and comp.GetToolList(False, "TextPlus"))
    except Exception:
        return False


def buscar_plantillas(mp):
    out = {}

    def recorrer(carpeta, en_plantillas=False, ruta=()):
        for c in carpeta.GetClipList() or []:
            p = _props_clip(c)
            tipo = p.get("type", "").lower()
            archivo = p.get("file path", "").lower()
            nombre = " ".join((p.get("clip name", ""), p.get("file name", ""),
                               str(c.GetName() or ""))).lower()
            if any(x in tipo for x in _TIPOS_NO_TEXTO) or archivo.endswith(".srt"):
                continue
            if any(x in nombre for x in _NOMBRES_NO_TEXTO):
                continue
            ok = (_tiene_textplus(c) or any(x in tipo for x in _TIPOS_CON_TEXTO)
                  or ("generator" in tipo and any(x in nombre for x in _NOMBRES_CON_TEXTO))
                  or (en_plantillas and (archivo.endswith((".setting", ".comp", ".drfx"))
                                          or any(x in nombre for x in _NOMBRES_CON_TEXTO))))
            if ok:
                out[" / ".join((*ruta, c.GetName()))] = c
        for f in carpeta.GetSubFolderList() or []:
            nombre = f.GetName().strip().lower()
            recorrer(f, en_plantillas or nombre in ("plantillas", "snap captions",
                                                    "plantilla", "templates", "template"),
                     (*ruta, f.GetName()))

    try:
        recorrer(mp.GetRootFolder())
    except Exception:
        pass
    return out


def elegir_plantilla(mp, preferida):
    tpls = buscar_plantillas(mp)
    if not tpls:
        return None
    if preferida:
        for etiqueta, clip in tpls.items():
            if preferida.lower() in etiqueta.lower() or etiqueta.lower() in preferida.lower():
                return clip
    # primera que tenga "text"/"caption" en el nombre
    for etiqueta, clip in tpls.items():
        if any(x in etiqueta.lower() for x in ("text", "caption", "titulo", "sub")):
            return clip
    return next(iter(tpls.values()))


def _textplus_de_item(item):
    try:
        comp = item.GetFusionCompByIndex(1)
    except Exception:
        comp = None
    if not comp:
        return None
    try:
        tools = comp.GetToolList(False, "TextPlus") or {}
    except Exception:
        return None
    return next(iter(tools.values()), None)


def _limpiar_pista(tl, pista, log):
    try:
        actuales = tl.GetItemListInTrack("video", pista) or []
        if actuales:
            tl.DeleteClips(actuales)
        restantes = tl.GetItemListInTrack("video", pista) or []
        if not restantes and tl.GetTrackCount("video") == pista:
            return bool(tl.DeleteTrack("video", pista))
        return not restantes
    except Exception as exc:
        log(f"[plantilla] no pude limpiar la pista parcial: {type(exc).__name__}: {exc}")
        return False


def aplicar_plantilla(tpl, bloques, tl, mp, fps, f_ini, progreso, log,
                      p_ini=92, p_fin=100):
    """Copia adaptada de subtitulos.py: insercion por lotes con rollback."""
    if not bloques:
        return 0
    total = len(bloques)
    num_lotes = 1 + max(0, math.ceil((total - 1) / _LOTE_INSERCION))
    progreso(p_ini, "Creando la pista de subtitulos en Resolve...")
    try:
        tl.AddTrack("video")
    except Exception as exc:
        raise RuntimeError(f"Resolve no pudo crear la pista de subtitulos: {exc}") from exc
    pista = tl.GetTrackCount("video")
    log(f"[plantilla] pista V{pista} creada; {total} titulos en {num_lotes} lotes")

    hechos, primera, lote = 0, True, 0
    while hechos < total:
        lote += 1
        tam = 1 if primera else min(_LOTE_INSERCION, total - hechos)
        tramo = bloques[hechos:hechos + tam]
        infos = [{"mediaPoolItem": tpl, "startFrame": 0,
                  "endFrame": max(1, round((e - s) * fps)),
                  "trackIndex": pista, "recordFrame": f_ini + round(s * fps)}
                 for _, s, e in tramo]
        progreso(p_ini + (p_fin - p_ini) * hechos / max(1, total),
                 f"Subtitulos: lote {lote}/{num_lotes} ({hechos}/{total})...")
        try:
            items = mp.AppendToTimeline(infos) or []
        except Exception as exc:
            _limpiar_pista(tl, pista, log)
            raise RuntimeError(f"Resolve fallo al insertar el lote {lote}: {exc}") from exc
        if len(items) != len(tramo):
            _limpiar_pista(tl, pista, log)
            raise RuntimeError(f"Resolve inserto {len(items)}/{len(tramo)} clips en el lote {lote}.")
        for item, (texto, _, _) in zip(items, tramo):
            tool = _textplus_de_item(item)
            if tool is None:
                _limpiar_pista(tl, pista, log)
                raise RuntimeError("La plantilla elegida no tiene un nodo Text+ editable.")
            tool.StyledText = texto
        hechos += tam
        primera = False
        time.sleep(0.005)
    log(f"[plantilla] {hechos}/{total} titulos insertados en V{pista}")
    return hechos


# ── Entrada principal ───────────────────────────────────────────────────
def ejecutar(resultado, cfg, progreso, log):
    """Genera los subtitulos sobre la timeline NUEVA y devuelve lineas de reporte."""
    import indie_cortes as C

    palabras = resultado["palabras_nueva"]
    if not palabras:
        return ["Subtitulos: no habia palabras alineadas; no se generaron."]

    grupos, limpios = grupos_del_guion(resultado["texto_guion"], resultado["G"])
    datos = []
    nombres = 0
    for texto, a, b, gi in palabras:
        gr, limpio = None, texto
        if isinstance(gi, int) and 0 <= gi < len(grupos):
            gr = grupos[gi]
            limpio = limpios[gi] or texto
        if gr is not None:
            nombres += 1
        datos.append([limpio, a, b, gr])
    bloques = armar_bloques(datos)
    log(f"Subtitulos: {len(bloques)} bloques, {nombres} palabras agrupadas en "
        f"nombres/canciones entre comillas, una palabra por bloque.")

    # Siempre se escribe el SRT (respaldo y para importarlo si hace falta).
    try:
        sello = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
        ruta_srt = os.path.join(K.LOGS_DIR, f"{K.nombre_seguro(resultado['tl_name'])}_{sello}_subs.srt")
        escribir_srt(bloques, ruta_srt)
        log("SRT de respaldo: " + ruta_srt)
    except Exception as exc:
        ruta_srt = ""
        log("No pude escribir el SRT de respaldo: " + str(exc))

    tl = resultado["nueva"]
    mp = C.mp
    fps = resultado["fps"]
    f_ini = tl.GetStartFrame()

    if cfg.get("srt_como_pista", False) or not cfg.get("generar_subtitulos", True):
        lineas = [f"Subtitulos: SRT listo ({len(bloques)} bloques). No se insertaron en la timeline."]
        if ruta_srt:
            lineas.append("SRT: " + ruta_srt)
        return lineas

    tpl = elegir_plantilla(mp, cfg.get("plantilla", ""))
    if tpl is None:
        lineas = [f"Subtitulos: no encontre una plantilla Text+ en el Media Pool. "
                  f"SRT listo ({len(bloques)} bloques) para importar a mano."]
        if ruta_srt:
            lineas.append("SRT: " + ruta_srt)
        return lineas

    try:
        n = aplicar_plantilla(tpl, bloques, tl, mp, fps, f_ini, progreso, log, 92, 99)
        return [f"Subtitulos: {n} bloques insertados en la timeline del reel "
                f"(una palabra por subtitulo, nombres entre comillas).",
                "SRT de respaldo: " + ruta_srt] if ruta_srt else [
                    f"Subtitulos: {n} bloques insertados en la timeline del reel."]
    except Exception as exc:
        log.error("No se pudieron insertar los subtitulos", exc)
        return [f"Subtitulos: fallo la insercion ({exc}). El SRT esta listo para importar: {ruta_srt}"]
