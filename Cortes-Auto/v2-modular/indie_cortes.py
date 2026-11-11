"""
Indie Now · NUEVO CORTE — motor de cortes
=========================================
Basado en cortes.py v5 (copia intacta en _base/cortes_v5_base.py).
NO modifica ni importa la carpeta de subs.

Mejoras de la Fase 2:
  P1  Distingue LECTURA de TOMA REAL: comentarios ("otra vez", "espera"),
      frases abandonadas, reinicios inmediatos, pausas de duda, volumen bajo.
      Elige la ULTIMA toma completa y fluida; si solo hay lectura, NO corta
      y marca la linea en rojo/rosa.
  P2  Cortes limpios: alinea inicio y fin al silencio real medido en el audio
      (envolvente de 10 ms). Nunca a mitad de palabra, nunca se come la "s".
  P3  faster-whisper en GPU via gpu_runtime, idioma configurable, glosario
      de nombres raros como initial_prompt, cache de transcripcion propio.
"""
from __future__ import annotations

from collections import defaultdict
import difflib
import hashlib
import math
import os
import pickle
import subprocess
import tempfile
import wave

import numpy as np

import indie_common as K
import gpu_runtime

# ── Ajustes por defecto (sobrescritos por config_cortes.json) ───────────
MODELO = "large-v3-turbo"
IDIOMA = "es"
PRE = 0.10
POST = 0.20
MIN_MATCH = 0.60
PAUSA_DUDA = 1.0
PENA_DUDA = 0.75
PAUSA_FRASE = 1.2
PAUSA = 0.5   # hueco max entre palabras contiguas (define piezas; cfg.pausa)
GAP_DUDOSA = 1.5
PENA_COMENTARIO = 4.0
PENA_REINICIO = 6.0
PENA_LENTA = 2.0
MAX_ANTES = 0.30
MAX_DESPUES = 0.35
PASO_ENV = 0.01

C_OK, C_DUDA, C_DIFIERE, C_FALTA, C_SIL = "Green", "Yellow", "Pink", "Red", "Blue"

# ── P1-v2: la señal de lectura es el VOLUMEN, no las pausas ─────────────
# El usuario lee el guion ~10-20 dB más bajo que cuando lo dice de verdad
# (LRA de la grabación ≈ 22 dB según Reaper). Una "pieza" = tramo de
# palabras contiguas (hueco <= pausa): se clasifica por su volumen MÁXIMO,
# así las tomas que arrancan suaves y suben se cuentan como reales.
PESO_REAL = 2.5      # por palabra del guion bien dicha (pieza con volumen)
PESO_FUZZY = 0.8     # por palabra emparejada difusa (nombres raros)
PESO_QUIETO = 0.3    # por palabra en pieza callada (se usa si no hay mejor toma)
BONO_PIEZA = 2.0     # por cada pieza real de la toma
BONO_COMPLETA = 8.0  # la toma cierra la oración del guion
BONO_ADY = 0.75      # toma pegada a la anterior (fluidez del reel)
BONO_ULTIMA = 0.6    # "última toma": rank entre candidatas de igual cobertura
PENA_SALTO = 2.0     # por palabra del guion que quedó sin audio

# Palabras/meta-comentarios que delatan un ensayo. Solo se cuentan FUERA del
# tramo emparejado con el guion (en los ±3 palabras de los bordes), para no
# confundir un "no" legitimo del guion con una duda.
COMENTARIOS = {
    "otra", "otro", "vez", "espera", "esperame", "esperate", "perdon", "perdón",
    "vamos", "listo", "dale", "corta", "corten", "reinicio", "repito", "toma",
    "eh", "em", "mm", "hmm", "mmm", "ay", "uff", "again", "wait", "sorry",
    "take", "okay", "vale", "bueno", "para", "pará", "sigo", "arranco",
}
COMENTARIOS_FRASES = {
    ("otra", "vez"), ("de", "nuevo"), ("otra", "toma"), ("un", "segundo"),
    ("espera", "un", "segundo"), ("vamos", "de", "nuevo"), ("no", "asi"),
}

ALUCINACIONES = [
    "graciasporverelvideo", "graciasporver", "suscribete", "subtitulosrealizadospor",
    "subtitulosporlacomunidad", "amaraorg", "graciasporvernos",
]

OPCIONES = [(1, 1), (0, 1), (1, 0), (2, 1), (1, 2), (2, 2), (2, 0), (3, 0)]
_FIN_FRASE: list[bool] = []

# ── Conexion con Resolve (se inicializa en ejecutar, no al importar) ─────
resolve = project = mp = timeline = None
FPS = TL_START = TL_NAME = None


def conectar():
    """Conecta con Resolve y expone las variables de modulo como en cortes v5."""
    global resolve, project, mp, timeline, FPS, TL_START, TL_NAME
    K.ruta_resolve_api()
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("No pude conectar con DaVinci Resolve. ¿Está abierto?")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No hay proyecto abierto en Resolve.")
    mp = project.GetMediaPool()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No hay timeline abierta en Resolve.")
    FPS = float(timeline.GetSetting("timelineFrameRate"))
    TL_START = timeline.GetStartFrame()
    TL_NAME = timeline.GetName()
    return timeline


# ── Cache de transcripcion (PROPIA: %LOCALAPPDATA%\IndieDL\cortes\cache) ─
def clave_cache(pista, f_ini, f_fin, prompt, modelo, idioma):
    partes = [modelo, idioma, prompt, str(FPS), str(f_ini), str(f_fin)]
    for it in timeline.GetItemListInTrack("audio", pista) or []:
        a, b = max(it.GetStart(), f_ini), min(it.GetEnd(), f_fin)
        if b <= a:
            continue
        mpi = it.GetMediaPoolItem()
        src = mpi.GetClipProperty("File Path") if mpi else ""
        try:
            tam = os.path.getsize(src)
        except OSError:
            tam = 0
        partes += [str(src), str(tam), str(it.GetLeftOffset() + (a - it.GetStart())), str(b - a)]
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()[:16]


def cache_leer(clave):
    try:
        with open(os.path.join(K.CACHE_DIR, clave + ".pkl"), "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def cache_guardar(clave, datos):
    try:
        os.makedirs(K.CACHE_DIR, exist_ok=True)
        with open(os.path.join(K.CACHE_DIR, clave + ".pkl"), "wb") as f:
            pickle.dump(datos, f)
    except Exception:
        pass


# ── Audio de la timeline ────────────────────────────────────────────────
def segmentos_audio(pista, f_ini, f_fin, tmp):
    segs = []
    for i, it in enumerate(timeline.GetItemListInTrack("audio", pista) or []):
        a, b = max(it.GetStart(), f_ini), min(it.GetEnd(), f_fin)
        if b <= a:
            continue
        src = it.GetMediaPoolItem().GetClipProperty("File Path")
        off = (it.GetLeftOffset() + (a - it.GetStart())) / FPS
        dur = (b - a) / FPS
        wav = os.path.join(tmp, f"seg{i}.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{off:.3f}", "-t", f"{dur:.3f}",
             "-i", src, "-ac", "1", "-ar", "16000", wav],
            check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        segs.append((wav, (a - f_ini) / FPS))
    return segs


def cargar_wav(path):
    with wave.open(path, "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


_ultimos = []


def es_alucinacion(seg):
    t = K.norm(seg.text)
    _ultimos.append(t)
    del _ultimos[:-3]
    if any(b in t for b in ALUCINACIONES) or t == "gracias":
        return True
    if len(_ultimos) == 3 and t and _ultimos[0] == _ultimos[1] == _ultimos[2]:
        return True
    return seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.8


# ── P3: transcripcion GPU + idioma + glosario ───────────────────────────
def transcribir(segs, prompt, progreso, log, modelo=MODELO, idioma=IDIOMA):
    from faster_whisper import WhisperModel

    dlls = []
    try:
        dlls = gpu_runtime.preparar_cuda()
    except Exception as exc:
        log(f"Aviso: no pude preparar CUDA ({type(exc).__name__}: {exc}); sigo igual.")
    if dlls:
        log(f"CUDA: {len(dlls)} carpeta(s) de DLL registradas.")
    gpu = gpu_runtime.nvidia_info()
    log(f"GPU detectada: {gpu or 'ninguna / nvidia-smi no disponible'}")

    device, compute = "cuda", "int8_float16"
    try:
        model = WhisperModel(modelo, device=device, compute_type=compute)
        log(f"faster-whisper '{modelo}' en GPU ({compute}).")
    except Exception as exc:
        log(f"Falló CUDA ({type(exc).__name__}: {exc}); reintento en CPU.")
        device, compute = "cpu", "int8"
        model = WhisperModel(modelo, device=device, compute_type=compute)
        log(f"faster-whisper '{modelo}' en CPU ({compute}) — más lento.")

    total = sum(
        float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", w], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip())
        for w, _ in segs
    ) or 1

    lang = None if idioma == "auto" else idioma
    log(f"Idioma: {lang or 'auto'} · prompt con {len(prompt.split())} palabras de glosario.")
    hecho, palabras, envs = 0.0, [], []
    for wav, t0 in segs:
        audio = cargar_wav(wav)
        n = len(audio) // 160
        if n:
            fr = audio[:n * 160].reshape(n, 160)
            envs.append((t0, 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-6)))
        it, info = model.transcribe(
            audio, language=lang, word_timestamps=True,
            initial_prompt=prompt or None, vad_filter=False, beam_size=5,
            condition_on_previous_text=False,
        )
        for s in it:
            progreso(35 + 45 * (hecho + s.end) / total, "Transcribiendo...")
            if es_alucinacion(s):
                continue
            for w in s.words or []:
                nw = K.norm(w.word)
                if nw:
                    palabras.append((nw, t0 + w.start, t0 + w.end))
        hecho += info.duration
    log(f"Transcripcion: {len(palabras)} palabras con timestamp.")
    return palabras, envs


def refinar(T, envs):
    """Whisper estira palabras sobre los silencios: ajusta al sonido real."""
    if not envs:
        return T
    umbral = np.percentile(np.concatenate([e for _, e in envs]), 10) + 12
    out = []
    for n, s, e in T:
        env = next(((t0, ev) for t0, ev in envs if t0 - 0.001 <= s < t0 + len(ev) * 0.01), None)
        if env is None:
            out.append((n, s, e))
            continue
        t0, ev = env
        a, b = max(0, int((s - t0) / 0.01)), min(len(ev), int(math.ceil((e - t0) / 0.01)))
        if b - a < 2:
            out.append((n, s, e))
            continue
        v = ev[a:b] > umbral
        runs, k = [], 0
        while k < len(v):
            if v[k]:
                m = k
                while m < len(v) and v[m]:
                    m += 1
                runs.append([k, m])
                k = m
            else:
                k += 1
        unidos = []
        for r in runs:
            if unidos and r[0] - unidos[-1][1] <= 15:
                unidos[-1][1] = r[1]
            else:
                unidos.append(r)
        unidos = [r for r in unidos if r[1] - r[0] >= 3]
        if not unidos:
            out.append((n, s, e))
            continue
        r = max(unidos, key=lambda r: r[1] - r[0])
        out.append((n, t0 + (a + r[0]) * 0.01, t0 + (a + r[1]) * 0.01))
    return [(n, s, min(e, s + 1.5)) for n, s, e in out]


def niveles(T, envs):
    """Volumen dB de cada palabra (para separar lectura de toma real)."""
    if not envs:
        return None
    out = []
    for n, s, e in T:
        env = next(((t0, ev) for t0, ev in envs if t0 - 0.001 <= s < t0 + len(ev) * 0.01), None)
        if env is None:
            out.append(float("nan"))
            continue
        t0, ev = env
        a = max(0, int((s - t0) / 0.01))
        b = min(len(ev), max(a + 1, int((e - t0) / 0.01)))
        out.append(float(np.percentile(ev[a:b], 90)))
    arr = np.array(out)
    med = float(np.nanmedian(arr)) if np.isfinite(arr).any() else 0.0
    return [med if not np.isfinite(x) else x for x in out]


# ── P2: mapa de silencio global ─────────────────────────────────────────
def mapa_silencio(envs, dur_total):
    """Devuelve (voz: bool[], umbral_db). 'voz[j]' = hay sonido en j*0.01 s."""
    n = int(dur_total / PASO_ENV) + 4
    db = np.full(n, -120.0, dtype=np.float32)
    for t0, ev in envs:
        k = int(round(t0 / PASO_ENV))
        m = min(len(ev), max(0, n - k))
        if m > 0 and k >= 0:
            db[k:k + m] = np.maximum(db[k:k + m], ev[:m])
    activos = db[db > -119]
    if activos.size == 0:
        return np.zeros(n, dtype=bool), 0.0
    umbral = float(np.percentile(activos, 15) + 10)
    return db > umbral, umbral


def _borde_inicio(s, voz, pre, max_antes):
    """Inicio del clip: punto medio del silencio anterior, sin meterse en la
    palabra de antes. Nunca despues del inicio real de la primera palabra."""
    k = max(1, int(s / PASO_ENV))
    a = k
    limite = max(0, k - int(max_antes / PASO_ENV))
    while a > limite and not voz[a - 1]:
        a -= 1
    silencio = (k - a) * PASO_ENV
    if silencio >= 0.06:
        punto = ((a + k) / 2.0) * PASO_ENV       # mitad del silencio
        return max(s - max_antes, min(s - 0.02, punto))
    return max(0.0, s - pre)


def _borde_fin(e, voz, post, max_despues):
    """Fin del clip: despues del ultimo sonido real de la palabra (protege la
    's' final) y en el silencio mas cercano, sin frames mudos de sobra."""
    k = max(1, int(e / PASO_ENV))
    k = min(k, len(voz) - 1)
    # ultimo frame con voz en una ventana corta alrededor del fin de palabra
    desde = max(0, k - int(0.15 / PASO_ENV))
    hasta = min(len(voz), k + int(0.12 / PASO_ENV))
    ultimo = k
    for j in range(hasta - 1, desde - 1, -1):
        if voz[j]:
            ultimo = j
            break
    e_real = max(e, (ultimo + 1) * PASO_ENV)
    # primer frame de la palabra siguiente
    b = min(len(voz) - 1, k)
    limite = min(len(voz) - 1, b + int(max_despues / PASO_ENV))
    while b < limite and not voz[b]:
        b += 1
    silencio = (b - k) * PASO_ENV
    if silencio >= 0.08:
        punto = ((k + b) / 2.0) * PASO_ENV + 0.06
        fin = min(e_real + post + 0.05, max(e_real + 0.06, punto))
    else:
        fin = e_real + post
    return max(e_real + 0.06, min(fin, e_real + max_despues))


# ── Alineacion guion <-> transcripcion ──────────────────────────────────
def extender(T, Tn, G, nl, i, g, pieza_id=None, pieza_max=None, thresh=None, pausa=PAUSA):
    ti, gi, ok, err, extra = i, g, 0, 0, []
    mejor = (0, i, 0, 0, [])
    la = i          # última palabra ACEPTADA (para el gate de volumen)
    nT, nG = len(Tn), len(G)
    while ti < nT and gi < nG:
        # Gate de volumen: si el hueco desde la última palabra aceptada abre
        # una pieza NUEVA callada, no se encadena (ahí solo hay lectura, o la
        # frase siguió en otra toma). Piezas con volumen SÍ se encadenan,
        # aunque haya pausas largas (frases dichas a trozos).
        if pieza_max is not None and ti > la \
                and T[ti][1] - T[la][2] > pausa and pieza_max[pieza_id[ti]] < thresh:
            break
        if gi > g and ti > i and gi - 1 < len(_FIN_FRASE) and _FIN_FRASE[gi - 1] \
                and T[ti][1] - T[ti - 1][2] > PAUSA_FRASE:
            break
        if Tn[ti] == G[gi]:
            ok += 1
            la = ti
            ti += 1
            gi += 1
            mejor = (gi - g, ti, ok, err, list(extra))
            continue
        for dt, dg in OPCIONES:
            if ti + dt < nT and gi + dg < nG and Tn[ti + dt] == G[gi + dg]:
                if dg == 0:
                    extra += range(ti, ti + dt)
                la = ti + dt
                ti += dt
                gi += dg
                err += max(dt, dg)
                break
        else:
            break
        if err > 2 and err > ok * 0.6:
            break
    cg, fin, ok, err, extra = mejor
    if cg and fin < nT and g + cg < nG and fin > i and Tn[fin] != G[g + cg] \
            and T[fin][1] - T[fin - 1][2] <= 0.3 \
            and nl[g + cg] and difflib.SequenceMatcher(None, Tn[fin], G[g + cg]).ratio() >= 0.2:
        cg, fin, err = cg + 1, fin + 1, err + 1
    return cg, fin, ok, err, extra


def sacar_extra(T, Tn, extra, recientes):
    extra, out, k = sorted(extra), set(), 0
    while k < len(extra):
        m = k
        while m + 1 < len(extra) and extra[m + 1] == extra[m] + 1:
            m += 1
        a, b = extra[k], extra[m]
        largas = [x for x in range(a, b + 1) if len(Tn[x]) >= 3]
        repite = bool(largas) and sum(Tn[x] in recientes for x in largas) >= 0.5 * len(largas)
        antes = a > 0 and T[a][1] - T[a - 1][2] > 0.3
        despues = b + 1 < len(T) and T[b + 1][1] - T[b][2] > 0.3
        if repite or antes or despues:
            out.update(range(a, b + 1))
        k = m + 1
    return out


def candidatos(T, Tn, pos, G, nl, g, lo, usados, ok_min=2,
               pieza_id=None, pieza_max=None, thresh=None, pausa=PAUSA):
    out = []
    for k in range(4):
        if g + k >= len(G) or (k and len(G[g + k]) < 3):
            continue
        for i in pos.get(G[g + k], []):
            if i < lo - 2:
                continue
            cg, fin, ok, err, extra = extender(T, Tn, G, nl, i, g + k,
                                               pieza_id, pieza_max, thresh, pausa)
            if ok < min(ok_min, len(G) - g) or fin <= i:
                continue
            ini, m = i, 0
            while m < k and ini - 1 >= 0 and T[ini][1] - T[ini - 1][2] <= 0.3 \
                    and not any(a <= ini - 1 < b for a, b in usados):
                ini -= 1
                m += 1
            if any(not (fin <= a or ini >= b) for a, b in usados):
                continue
            out.append({
                "i": ini, "fin": fin, "cubre": k + cg, "ok": ok, "err": err,
                "k": k, "m": m,
                "extra_todas": set(extra),
                "extra": sacar_extra(T, Tn, extra, set(G[max(0, g - 15):g + 15])),
            })
    return out


# ── P1: señales de LECTURA ──────────────────────────────────────────────
def _comentarios_cerca(T, Tn, c, vocab, ventana=0.8):
    """Meta-comentarios PEGADOS EN EL TIEMPO a los bordes de la toma.

    El gate temporal es clave: sin él, un 'espera' que pertenece a la toma
    siguiente (varios segundos despues) contaminaba a una toma limpia y la
    marcaba como lectura. Solo cuentan palabras a < 'ventana' segundos del
    borde y que no figuren en el vocabulario del guion.
    """
    t_ini = T[c["i"]][1]
    t_fin = T[c["fin"] - 1][2]
    idx = []
    for k in range(max(0, c["i"] - 3), c["i"]):
        if t_ini - T[k][2] <= ventana:
            idx.append(k)
    for k in range(c["fin"], min(len(Tn), c["fin"] + 3)):
        if T[k][1] - t_fin <= ventana:
            idx.append(k)
    n = 0
    for k in idx:
        if Tn[k] in COMENTARIOS and Tn[k] not in vocab:
            n += 1
        for L in (3, 2):
            if tuple(Tn[k:k + L]) in COMENTARIOS_FRASES:
                n += 1
                break
    return n


def _reinicio_inmediato(T, Tn, c, G, g, max_gap=2.0):
    """La misma frase del guion vuelve a empezar apenas termina esta toma:
    esta era un arranque en falso / lectura, y la buena viene despues."""
    frag = [G[g + k][0] for k in range(min(3, c["cubre"]))]
    if len(frag) < 2:
        return False
    t_fin = T[c["fin"] - 1][2]
    for k in range(c["fin"], min(len(Tn), c["fin"] + 50)):
        if T[k][1] - t_fin > max_gap:
            break
        if list(Tn[k:k + len(frag)]) == frag:
            return True
    return False


def _llega_a_fin_de_frase(G, g, cubre):
    """La toma cubre la oracion completa del guion (termina limpia)."""
    if cubre <= 0:
        return False
    d = G[min(len(G) - 1, g + cubre - 1)][1]
    return d.rstrip("”\"’)»").endswith((".", "?", "!", "…"))


def _piezas(T, i, j, pausa):
    """[(a, b)] tramos de palabras contiguas (hueco <= pausa) en [i, j)."""
    out, a = [], None
    for k in range(i, j):
        if a is None:
            a = k
        elif T[k][1] - T[k - 1][2] > pausa:
            out.append((a, k))
            a = k
    if a is not None:
        out.append((a, j))
    return out


def clasificar_tomas(T, Tn, cs, G, g, niv, thresh, pausa, vocab, modo):
    """Anota cada candidata con su perfil de volumen y ajusta su score.

    El volumen se mide por PIEZA (max de la pieza): una pieza es "real" si
    llega al nivel de la voz fuerte. Una toma toda callada es una lectura...
    salvo que sea la única toma de esa frase (entonces se usa, como en el
    reel hecho a mano). Las pausas ya NO descartan: es normal decir frases
    a trozos, y el gate de extender() ya evita encadenar piezas calladas.
    """
    # bonus "última toma": rank por posición entre candidatas con la MISMA
    # cobertura (la de más acá es la re-grabada; las de antes son tomas viejas)
    por_clase = defaultdict(list)
    for c in cs:
        por_clase[c["cubre"]].append(c["i"])
    bono_rank = {}
    for cubre, idxs in por_clase.items():
        for r, idx in enumerate(sorted(set(idxs))):
            bono_rank[idx] = BONO_ULTIMA * r if modo == "ultima" else 0.0

    for c in cs:
        c["piezas"] = _piezas(T, c["i"], c["fin"], pausa)
        c["reales"], c["calladas"] = [], []
        for a, b in c["piezas"]:
            mx = max(niv[a:b]) if niv else 0.0
            (c["reales"] if mx >= thresh else c["calladas"]).append((a, b, mx))
        c["baja"] = bool(niv and not c["reales"])

        match_r = match_q = 0
        for a, b, _mx in c["reales"]:
            match_r += sum(1 for k in range(a, b) if k not in c["extra_todas"])
        for a, b, _mx in c["calladas"]:
            match_q += sum(1 for k in range(a, b) if k not in c["extra_todas"])
        c["match_r"] = match_r
        c["ok_real"] = min(c["ok"], match_r)
        dur_r = sum(T[b - 1][2] - T[a][1] for a, b, _mx in c["reales"]) or 0.1
        c["wps"] = match_r / max(0.1, dur_r)

        c["comentarios"] = _comentarios_cerca(T, Tn, c, vocab)
        c["reinicio"] = _reinicio_inmediato(T, Tn, c, G, g)
        c["completa"] = _llega_a_fin_de_frase(G, g, c["cubre"])

        # sin audio para las palabras de guion que saltea el ancla (k - m)
        sin_audio = (c.get("k", 0) - c.get("m", 0)) * PENA_SALTO

        c["score"] = (
            PESO_REAL * c["ok_real"]
            + PESO_FUZZY * max(0, match_r - c["ok_real"])
            + PESO_QUIETO * match_q
            + BONO_PIEZA * len(c["reales"])
            + (BONO_COMPLETA if c["completa"] else 0.0)
            + bono_rank.get(c["i"], 0.0)
            - PENA_COMENTARIO * min(c["comentarios"], 2)
            - (PENA_REINICIO if c["reinicio"] else 0.0)
            - sin_audio
        )

        razones = []
        if c["baja"]:
            razones.append("toma callada (volumen de lectura)")
        elif c["calladas"]:
            razones.append(f"{len(c['calladas'])} pieza(s) callada(s)")
        if c["comentarios"]:
            razones.append(f"comentario de ensayo x{c['comentarios']}")
        if c["reinicio"]:
            razones.append("arranque en falso (la frase se repite enseguida)")
        c["razon"] = ", ".join(razones)
    return cs


def cortes_de_toma(T, i, j, pausa, voz, excluir=(), pre=PRE, post=POST,
                   max_antes=MAX_ANTES, max_despues=MAX_DESPUES):
    """P2: segundos (inicio, fin) de una toma, con bordes ajustados al silencio.
    Nunca corta a mitad de palabra: inicio <= primer inicio de palabra y
    fin >= ultimo sonido real de la ultima palabra (protege la 's' final)."""
    piezas, a = [], None
    for k in range(i, j):
        if k in excluir:
            if a is not None:
                piezas.append((a, k))
                a = None
            continue
        if a is None:
            a = k
        elif T[k][1] - T[k - 1][2] > pausa:
            piezas.append((a, k))
            a = k
    if a is not None:
        piezas.append((a, j))
    out = []
    for a, b in piezas:
        # recorta el padding para no meter silencio de la palabra vecina
        p_pre, p_post = pre, post
        if a > 0:
            p_pre = min(p_pre, max(0.0, (T[a][1] - T[a - 1][2]) / 2))
        if b < len(T):
            p_post = min(p_post, max(0.0, (T[b][1] - T[b - 1][2]) / 2))
        ini = _borde_inicio(T[a][1], voz, p_pre, max_antes)
        fin = _borde_fin(T[b - 1][2], voz, p_post, max_despues)
        out.append((max(0.0, ini), fin))
    return out


def diferencias(a, b, maxlen=140):
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, [x[0] for x in a], [x[0] for x in b], autojunk=False).get_opcodes():
        if tag == "replace":
            out.append(f"{' '.join(x[1] for x in a[i1:i2])} -> {' '.join(x[1] for x in b[j1:j2])}")
        elif tag == "delete":
            out.append("no dice: " + " ".join(x[1] for x in a[i1:i2]))
        elif tag == "insert":
            out.append("de mas: " + " ".join(x[1] for x in b[j1:j2]))
    txt = "; ".join(out)
    return txt if len(txt) <= maxlen else txt[:maxlen - 3] + "..."


def planear(T, G, modo, pausa, voz, niv=None, bajada=0.0,
            pre=PRE, post=POST, max_antes=MAX_ANTES, max_despues=MAX_DESPUES):
    """Devuelve (cortes, reporte, traza, eventos, palabras_para_subs, lecturas)."""
    Tn = [t[0] for t in T]
    palabras = [w for w, _ in G]
    vocab = sorted(set(palabras))
    vs, cache = set(vocab), {}
    for k, w in enumerate(Tn):
        if w not in vs:
            if w not in cache:
                # nombres raros (daneses, griegos, ingleses): fuzzy mas laxo
                cutoff = 0.72 if len(w) >= 5 else 0.82
                m = difflib.get_close_matches(w, vocab, n=1, cutoff=cutoff)
                cache[w] = m[0] if m else w
            Tn[k] = cache[w]
    pos = defaultdict(list)
    for i, w in enumerate(Tn):
        pos[w].append(i)
    _FIN_FRASE[:] = [d.rstrip("”\"’)»").endswith((".", "?", "!", "…")) for _, d in G]
    nl = []
    for k, (_, d) in enumerate(G):
        ini = k == 0 or G[k - 1][1].rstrip("”\"’)").endswith((".", "?", "!", "…"))
        nl.append(d.lstrip("“\"‘¿¡(")[:1].isupper() and not ini)
    ref = None
    if niv and bajada > 0:
        ref = float(np.percentile(niv, 75))
    thresh = (ref - bajada) if ref is not None else None

    # piezas GLOBALES: un hueco > pausa separa piezas; cada pieza guarda su
    # volumen maximo (senal de lectura vs toma real)
    pieza_id = [0] * len(T)
    pieza_max = []
    p = -1
    for k in range(len(T)):
        if k == 0 or T[k][1] - T[k - 1][2] > pausa:
            p += 1
            pieza_max.append(-99.0)
        pieza_id[k] = p
        if niv:
            pieza_max[p] = max(pieza_max[p], niv[k])
    vocab_set = set(vocab)

    traza, eventos, falta_actual = [], [], []
    palabras_para_subs = []       # (indice_T, indice_guion, texto_mostrar, s_orig, e_orig)
    cortes, faltan, usados = [], [], []
    lecturas_descartadas = []
    varias, tramos = 0, 0

    def cerrar_faltas(t_anclaje, motivo="El guion dice y no lo encontre"):
        if falta_actual:
            faltan.extend(falta_actual)
            txt = " ".join(G[k][1] for k in falta_actual)
            eventos.append({"t": t_anclaje, "color": C_FALTA, "nombre": "FALTA EN EL AUDIO",
                            "nota": f"{motivo}: {txt[:200]}"})
            falta_actual.clear()

    _cand = {}

    def cand(gi):
        """Candidatas para la posicion `gi` del guion (cacheadas)."""
        if gi not in _cand:
            cs = candidatos(T, Tn, pos, palabras, nl, gi, 0, (), 2,
                            pieza_id, pieza_max, thresh, pausa)
            clasificar_tomas(T, Tn, cs, G, gi, niv, thresh, pausa, vocab_set, modo)
            if not cs:
                # segunda pasada laxa: frases de una sola palabra
                cs = candidatos(T, Tn, pos, palabras, nl, gi, 0, (), 1,
                                pieza_id, pieza_max, thresh, pausa)
                clasificar_tomas(T, Tn, cs, G, gi, niv, thresh, pausa, vocab_set, modo)
                # de 1 palabra solo se aceptan piezas con volumen (evita
                # meter ruido callado); de 2 o mas palabras se acepta todo
                cs = [c for c in cs if c["cubre"] >= 2 or c["reales"]]
            _cand[gi] = cs
        return _cand[gi]

    # ── DP: elegir tomas con ORDEN GLOBAL ───────────────────────────────
    # estado = (posicion del guion, fin_T de la ultima toma elegida).
    # Garantiza tomas en orden y sin superponerse, y que "ultima toma"
    # NUNCA salte a una frase igual que aparece al final del video.
    N = len(palabras)
    dp = {0: {0: (0.0, None)}}
    for gg in range(N):
        estados = dp.get(gg)
        if not estados:
            continue
        cs = cand(gg)
        for fin_prev, (sc, _b) in estados.items():
            # opcion A: saltear la palabra (no hay audio / no vale la pena)
            nuevo = sc - PENA_SALTO
            nxt = dp.setdefault(gg + 1, {})
            if fin_prev not in nxt or nuevo > nxt[fin_prev][0]:
                nxt[fin_prev] = (nuevo, (gg, fin_prev, "salto", None))
            # opcion B: usar una toma (avanza cubre palabras del guion)
            for c in cs:
                if c["i"] < fin_prev:
                    continue
                bono = BONO_ADY if (fin_prev and c["i"] - fin_prev <= 1) else 0.0
                s = sc + c["score"] + bono
                ng = min(N, gg + max(1, c["cubre"]))
                nxt2 = dp.setdefault(ng, {})
                if c["fin"] not in nxt2 or s > nxt2[c["fin"]][0]:
                    nxt2[c["fin"]] = (s, (gg, fin_prev, "toma", c))
    finales = dp.get(N) or {}
    if not finales:
        raise RuntimeError("El plan de cortes quedo vacio.")
    mejor_fin = max(finales, key=lambda f: finales[f][0])

    acciones = []
    gg_cur, fin_cur = N, mejor_fin
    while gg_cur > 0:
        _sc, back = dp[gg_cur][fin_cur]
        acciones.append(back)
        gg_cur, fin_cur = back[0], back[1]
    acciones.reverse()

    for gg, _fin_prev, tipo, c in acciones:
        if tipo == "salto":
            falta_actual.append(gg)
            continue
        cs = cand(gg)
        # palabras del guion que el ancla salteo y no tienen audio
        sin_audio = max(0, c.get("k", 0) - c.get("m", 0))
        for w in range(gg, gg + sin_audio):
            falta_actual.append(w)
        incl = [k for k in range(c["i"], c["fin"]) if k not in c["extra_todas"]]
        ini_real = incl[0] if incl else c["i"]
        t_ini = T[ini_real][1]
        cerrar_faltas(t_ini)

        improv = len(c["extra_todas"] - c["extra"])
        dif = max(0, (c["cubre"] - c["ok"]) + improv)
        otras = [x for x in cs if x is not c and (x["fin"] <= c["i"] or x["i"] >= c["fin"])]
        gap = (c["score"] - max(x["score"] for x in otras)) if otras else 99
        txt_guion = f"Guion: {' '.join(d for _, d in G[gg:gg + c['cubre']])[:110]}"

        if c["baja"]:
            eventos.append({"t": t_ini, "color": C_DIFIERE,
                            "nombre": "SOLO LECTURA (SE USA IGUAL)",
                            "nota": "No hay toma con volumen de esta frase; "
                                    f"se usa la lectura.\n{txt_guion}"})
        elif dif > 0:
            razon = diferencias(G[gg:gg + c["cubre"]], [(Tn[k], T[k][0]) for k in incl])
            eventos.append({"t": t_ini, "color": C_DIFIERE, "nombre": "DIFIERE DEL GUION",
                            "nota": f"{razon}\n{txt_guion}"})
        elif otras and gap < GAP_DUDOSA:
            distintas, fin_d = [], -1
            for x in sorted(otras, key=lambda x: x["i"]):
                if x["i"] >= fin_d:
                    distintas.append(x)
                    fin_d = x["fin"]
            donde = ", ".join(K.mmss(T[x["i"]][1]) for x in distintas[:3])
            eventos.append({"t": t_ini, "color": C_DUDA, "nombre": "VARIAS TOMAS PARECIDAS",
                            "nota": f"Use la de {K.mmss(t_ini)}. Otras en la original: {donde}\n{txt_guion}"})
        else:
            eventos.append({"t": t_ini, "color": C_OK, "nombre": "OK", "nota": txt_guion})

        # tomas de lectura descartadas para el reporte
        for x in cs:
            if x is not c and (x["baja"] or x["comentarios"] or x["reinicio"]) \
                    and len(lecturas_descartadas) < 60:
                lecturas_descartadas.append((T[x["i"]][1], "", x["razon"]))

        # palabras para subtitulos: texto del guion cuando coincide (corrige
        # nombres raros mal oidos), con tiempos de la transcripcion real.
        gi0 = gg + c.get("k", 0) - c.get("m", 0)
        for off, k in enumerate(incl):
            gi = gi0 + off
            if 0 <= gi < len(G) and Tn[k] == G[gi][0]:
                texto = G[gi][1]
            else:
                texto = T[k][0]
            palabras_para_subs.append((k, gi, texto, T[k][1], T[k][2]))

        usados.append((c["i"], c["fin"]))
        cortes += cortes_de_toma(T, c["i"], c["fin"], pausa, voz, c["extra"],
                                 pre, post, max_antes, max_despues)
        traza.append(
            f"{t_ini:7.1f}s  g={gg:3} guion: {' '.join(palabras[gg:gg + c['cubre']])[:70]}\n"
            f"            toma: {' '.join(Tn[c['i']:c['fin']])[:70]}\n"
            f"            ok={c['ok']} real={c['ok_real']} score={c['score']:.1f} "
            f"completa={c['completa']} piezas={len(c['reales'])}r/{len(c['calladas'])}c "
            f"baja={c['baja']} coment={c['comentarios']}"
        )
        tramos += 1
        buenas = [x for x in otras if x["ok"] >= max(2, 0.6 * c["ok"])]
        distintas_n, fin_d2 = 0, -1
        for x in sorted(buenas, key=lambda x: x["i"]):
            if x["i"] >= fin_d2:
                distintas_n += 1
                fin_d2 = x["fin"]
        varias += distintas_n >= 1
    cerrar_faltas(None)

    unidos = []
    for a, b in cortes:
        if unidos and -0.02 <= a - unidos[-1][1] <= 0.15:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], b))
        else:
            unidos.append((a, b))
    rep = [
        f"{len(palabras) - len(set(faltan))} de {len(palabras)} palabras del guion estan, en orden.",
        f"{len(unidos)} cortes · {varias} de {tramos} tramos tenian mas de una toma.",
    ]
    if lecturas_descartadas:
        rep.append(f"Lecturas / arranques en falso descartados: {len(lecturas_descartadas)}.")
    if thresh is not None:
        rep.append(f"Tu voz fuerte ≈ {ref:.0f} dB. Se descartan tomas cuyas piezas quedan bajo {thresh:.0f} dB (lecturas).")
    if faltan:
        grupos, cur = [], [sorted(set(faltan))[0]]
        for k in sorted(set(faltan))[1:]:
            if k == cur[-1] + 1:
                cur.append(k)
            else:
                grupos.append(cur)
                cur = [k]
        grupos.append(cur)
        rep.append("No encontre en el audio (no se incluye):")
        rep += ["  - " + " ".join(G[k][1] for k in gr) for gr in grupos]
    return unidos, rep, traza, eventos, palabras_para_subs, lecturas_descartadas


# ── Armar la timeline nueva ─────────────────────────────────────────────
def carpeta_de_timeline():
    uid = None
    try:
        mpi = timeline.GetMediaPoolItem()
        uid = mpi.GetUniqueId() if mpi else None
    except Exception:
        pass
    por_nombre = []

    def buscar(carpeta):
        for c in carpeta.GetClipList() or []:
            try:
                if uid and c.GetUniqueId() == uid:
                    return carpeta
                if c.GetName() == TL_NAME and "timeline" in (c.GetClipProperty("Type") or "").lower():
                    por_nombre.append(carpeta)
            except Exception:
                pass
        for f in carpeta.GetSubFolderList() or []:
            r = buscar(f)
            if r:
                return r
        return None

    return buscar(mp.GetRootFolder()) or (por_nombre[0] if por_nombre else None)


def _fps_clip(mpi):
    try:
        v = float(mpi.GetClipProperty("FPS"))
        return v if v > 0 else FPS
    except Exception:
        return FPS


def infos_pista(tipo, pista, cortes_f, rec0, destino=1):
    items = timeline.GetItemListInTrack(tipo, pista) or []
    out, acum = [], 0
    for a, b in cortes_f:
        for it in items:
            aa, bb = max(a, it.GetStart()), min(b, it.GetEnd())
            if bb <= aa:
                continue
            mpi = it.GetMediaPoolItem()
            if not mpi:
                continue
            f = _fps_clip(mpi)
            sf = round((it.GetLeftOffset() + (aa - it.GetStart())) / FPS * f)
            n = max(1, round((bb - aa) / FPS * f))
            out.append({"mediaPoolItem": mpi, "startFrame": sf, "endFrame": sf + n - 1,
                        "mediaType": 1 if tipo == "video" else 2, "trackIndex": destino,
                        "recordFrame": rec0 + acum + (aa - a)})
        acum += b - a
    return out


def pos_en_nueva(cortes_f, frame_orig):
    acum = 0
    for a, b in cortes_f:
        if a <= frame_orig < b:
            return acum + (frame_orig - a)
        acum += b - a
    return None


def _mapear_tiempo(cortes_f, seg_orig, f_ini):
    """Segundo en la timeline NUEVA de un segundo del rango original."""
    fr = f_ini + round(seg_orig * FPS)
    pos = pos_en_nueva(cortes_f, fr)
    return None if pos is None else pos / FPS


def poner_marca(tl, frame, color, nombre, nota, dur=1):
    base = tl.GetStartFrame()
    for k in range(8):
        for c in (color,):
            try:
                if tl.AddMarker(base + int(frame) + k, c, nombre, nota,
                                max(1, int(dur)), K.CUSTOM_MARCA):
                    return True
            except Exception:
                pass
    return False


def construir(cortes_f, pista_audio, pista_video, otras, log):
    nombre, n = f"{TL_NAME} - REEL", 1
    previa = mp.GetCurrentFolder()
    try:
        destino = carpeta_de_timeline()
        if destino:
            mp.SetCurrentFolder(destino)
        nueva = None
        while not nueva and n < 20:
            nueva = mp.CreateEmptyTimeline(nombre if n == 1 else f"{nombre} {n}")
            n += 1
    finally:
        if previa:
            mp.SetCurrentFolder(previa)
    if not nueva:
        raise RuntimeError("No pude crear la timeline nueva.")
    project.SetCurrentTimeline(nueva)
    rec0 = nueva.GetStartFrame()
    v = infos_pista("video", pista_video, cortes_f, rec0, 1)
    a = infos_pista("audio", pista_audio, cortes_f, rec0, 1)
    extras, dest = [], 2
    if otras:
        for t in range(1, timeline.GetTrackCount("audio") + 1):
            if t == pista_audio:
                continue
            info = infos_pista("audio", t, cortes_f, rec0, dest)
            if info:
                while nueva.GetTrackCount("audio") < dest:
                    nueva.AddTrack("audio")
                extras.append((dest, info))
                dest += 1
    ok_v = (not v) or bool(mp.AppendToTimeline(v))
    ok_a = (not a) or bool(mp.AppendToTimeline(a))
    for d, info in extras:
        ok_a = bool(mp.AppendToTimeline(info)) and ok_a
        try:
            nueva.SetTrackEnable("audio", d, False)
        except Exception:
            pass
    log(f"Timeline '{nueva.GetName()}': {len(v)} trozos de video, {len(a)} de audio, "
        f"{len(extras)} pistas extra desactivadas. ok_v={ok_v} ok_a={ok_a}")
    return nueva, ok_v, ok_a, len(v), len(a), len(extras)


# ── Proceso principal ───────────────────────────────────────────────────
def ejecutar(cfg, progreso, log):
    """Corta y devuelve todo lo que necesitan subtitulos + verificacion."""
    global MODELO, IDIOMA, PRE, POST
    MODELO = cfg.get("modelo", MODELO)
    IDIOMA = cfg.get("idioma", IDIOMA)
    PRE = float(cfg.get("pre", PRE))
    POST = float(cfg.get("post", POST))
    max_antes = float(cfg.get("padding_max_antes", MAX_ANTES))
    max_despues = float(cfg.get("padding_max_despues", MAX_DESPUES))

    conectar()
    log.paso("1 · Guion y rango")
    ruta_guion = cfg["guion"]
    if not os.path.isfile(ruta_guion):
        raise FileNotFoundError("No encuentro el guion: " + ruta_guion)
    texto = K.leer_guion(ruta_guion)
    G = K.palabras_del_guion(texto)
    if not G:
        raise RuntimeError("No pude sacar palabras del guion (¿formato/cabeceras?).")
    log(f"Guion: {os.path.basename(ruta_guion)} · {len(G)} palabras · "
        f"{len(K.lineas_del_guion(texto))} lineas (cabeceras y MAYUSCULAS ignoradas)")

    mi = timeline.GetMarkInOut() or {}
    ai = mi.get("audio") or mi.get("video") or {}
    if cfg.get("rango", "inout") == "inout" and ai and int(ai.get("out", 0)) > int(ai.get("in", 0)):
        f_ini, f_fin = int(ai["in"]), int(ai["out"])
        tipo = "In/Out"
    else:
        f_ini, f_fin = TL_START, timeline.GetEndFrame()
        tipo = "linea completa"
    if f_fin <= f_ini:
        raise RuntimeError("El rango de la timeline está vacío.")
    dur_total = (f_fin - f_ini) / FPS
    log(f"Timeline: {TL_NAME} · {FPS:g} fps · rango {tipo} {K.mmss(dur_total)} · "
        f"frames {f_ini}-{f_fin}")

    pista = int(cfg.get("pista_audio", 1))
    p_video = int(cfg.get("pista_video", 1))
    n_audio = timeline.GetTrackCount("audio")
    if not (1 <= pista <= n_audio):
        raise RuntimeError(f"A{pista} no existe (hay {n_audio} pistas de audio).")

    log.paso("2 · Transcripcion (GPU + cache)")
    glosario = K.glosario_del_guion(texto)
    prompt = " ".join(dict.fromkeys(glosario + [d for _, d in G]))[:600]
    clave = clave_cache(pista, f_ini, f_fin, prompt, MODELO, IDIOMA)
    datos = cache_leer(clave) if cfg.get("usar_cache", True) else None
    if datos:
        T, envs = datos
        log("Usando la transcripcion guardada (el audio no cambio) — 0 s de GPU.")
        progreso(80, "Usando la transcripción guardada...")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            progreso(5, "Extrayendo audio...")
            log("Extrayendo audio de la timeline con FFmpeg...")
            segs = segmentos_audio(pista, f_ini, f_fin, tmp)
            if not segs:
                raise RuntimeError("No hay audio en esa pista/rango.")
            progreso(30, "Cargando modelo en GPU...")
            T, envs = transcribir(segs, prompt, progreso, log, MODELO, IDIOMA)
        if not T:
            raise RuntimeError("Whisper no transcribio nada.")
        cache_guardar(clave, (T, envs))
        log(f"Transcripcion guardada en cache propia: {os.path.join(K.CACHE_DIR, clave + '.pkl')}")
    if not T:
        raise RuntimeError("La transcripcion quedo vacia.")
    T = refinar(T, envs)
    niv = niveles(T, envs)
    voz, umbral = mapa_silencio(envs, dur_total)
    log(f"Palabras refinadas: {len(T)} · umbral de voz {umbral:.1f} dB · mapa de silencio listo")

    log.paso("3 · Elegir la mejor toma real de cada linea (orden global)")
    cortes, rep, traza, eventos, pal_subs, lecturas = planear(
        T, G, cfg.get("modo", "ultima"), float(cfg.get("pausa", 0.5)), voz,
        niv, float(cfg.get("bajada_db", 8.0)), PRE, POST, max_antes, max_despues,
    )
    if not cortes:
        raise RuntimeError("No encontre ninguna frase del guion en el audio.")
    for linea in rep:
        log(linea)
    log(f"Cortes propuestos: {len(cortes)} · lecturas descartadas: {len(lecturas)}")

    cortes_f = []
    for a, b in cortes:
        fa = max(f_ini, f_ini + round(a * FPS))
        fb = min(f_fin, f_ini + round(b * FPS))
        if fb > fa:
            cortes_f.append((fa, fb))
    dur_final = sum(b - a for a, b in cortes_f) / FPS
    log(f"Duracion final del reel: {K.mmss(dur_final)} (de {K.mmss(dur_total)})")

    # Diagnostico
    try:
        sello = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
        ruta = os.path.join(K.LOGS_DIR, f"{K.nombre_seguro(TL_NAME)}_{sello}_cortes_debug.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(f"{K.VERSION}\n\n" + "\n".join(rep) + "\n\n=== TRAMOS ELEGIDOS ===\n" + "\n".join(traza))
            f.write("\n\n=== LECTURAS DESCARTADAS ===\n")
            for t, txt, razon in lecturas:
                f.write(f"{K.mmss(t):>7}  {txt}  [{razon}]\n")
            f.write("\n\n=== MARCADORES (posicion en la original) ===\n")
            for ev in eventos:
                if ev["color"] != C_OK:
                    f.write(f"{K.mmss(ev['t']) if ev['t'] is not None else 'final':>7}  "
                            f"{ev['color']:7} {ev['nombre']}: {ev['nota'].splitlines()[0]}\n")
            f.write("\n\n=== TRANSCRIPCION (seg, volumen dB, palabra) ===\n")
            for k, (n, s0, e0) in enumerate(T):
                f.write(f"{s0:7.2f} {e0:7.2f} {niv[k] if niv else 0:6.1f}  {n}\n")
        log("Diagnostico: " + ruta)
    except Exception as exc:
        log("No pude guardar el diagnostico: " + str(exc))

    log.paso("4 · Armar la timeline del reel en Resolve")
    progreso(90, "Armando la timeline nueva...")
    nueva, ok_v, ok_a, nv, na, ne = construir(
        cortes_f, pista, p_video, bool(cfg.get("copiar_otras_pistas", False)), log)

    # Palabras mapeadas a la timeline NUEVA (para subtitulos y verificacion)
    palabras_nueva = []
    for k, gi, texto, s0, e0 in pal_subs:
        a = _mapear_tiempo(cortes_f, s0, f_ini)
        b = _mapear_tiempo(cortes_f, e0, f_ini)
        if a is None or b is None:
            continue
        palabras_nueva.append([texto, a, max(b, a + 0.05), gi])

    # Marcadores, con minuto en la timeline NUEVA para el reporte
    progreso(96, "Poniendo marcadores...")
    try:
        nueva.DeleteMarkerByCustomData(K.CUSTOM_MARCA)
    except Exception:
        pass
    cuenta, fallos = defaultdict(int), 0
    lineas_dudosas = []
    for ev in eventos:
        if ev["color"] == C_OK and not cfg.get("marcar_ok", False):
            continue
        if ev["t"] is None:
            pos = max(0, sum(b - a for a, b in cortes_f) - 1)
        else:
            pos = pos_en_nueva(cortes_f, f_ini + round(ev["t"] * FPS))
        if pos is not None:
            minuto = K.mmss(pos / FPS)
            if ev["color"] in (C_FALTA, C_DIFIERE, C_DUDA):
                lineas_dudosas.append({
                    "minuto": minuto, "color": ev["color"], "nombre": ev["nombre"],
                    "nota": ev["nota"].splitlines()[0],
                })
        else:
            minuto = "fuera de corte"
        if pos is None or not poner_marca(nueva, pos or 0, ev["color"], ev["nombre"], ev["nota"]):
            fallos += 1
            continue
        cuenta[ev["color"]] += 1
    rep.append(f"Marcadores: rojo {cuenta[C_FALTA]} (falta), rosa {cuenta[C_DIFIERE]} (difiere), "
               f"amarillo {cuenta[C_DUDA]} (varias tomas)" +
               (f", verde {cuenta[C_OK]} (ok)" if cfg.get("marcar_ok") else "") +
               (f". {fallos} no se pudieron poner." if fallos else "."))
    rep.append(f"Timeline creada: {nueva.GetName()} ({nv} trozos de video, {na} de audio" +
               (f", {ne} pistas extra desactivadas)." if ne else ")."))
    if nv == 0:
        rep.append("OJO: no encontre video en esa pista de video.")
    if not (ok_v and ok_a):
        rep.append("OJO: Resolve rechazo parte de los clips. Revisa la timeline.")

    return {
        "nueva": nueva, "cortes_f": cortes_f, "G": G, "texto_guion": texto,
        "palabras_nueva": palabras_nueva, "eventos": eventos, "rep": rep,
        "lineas_dudosas": sorted(lineas_dudosas, key=lambda x: x["minuto"]),
        "lecturas": lecturas, "f_ini": f_ini, "f_fin": f_fin,
        "dur_total": dur_total, "dur_final": dur_final,
        "fps": FPS, "tl_start": TL_START, "tl_name": TL_NAME,
        "guion": ruta_guion, "total_cortes": len(cortes_f),
    }
