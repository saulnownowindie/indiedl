"""
Indie Now - Cortes automaticos v1 (DaVinci Resolve Studio, Windows)

MANDA LO QUE SE DICE. El guion solo se usa para:
  - corregir la escritura de lo transcripto (nombres, tildes, palabras mal oidas),
  - saber si lo dicho esta en el guion y en que orden (marcadores), y
  - detectar lecturas del guion en voz baja.

Que hace:
  1. Transcribe el audio del microfono (una pista de la timeline abierta).
  2. Separa en frases y mide el volumen de cada una contra el volumen LOCAL del microfono
     (se adapta si el microfono se acerca o se aleja). Lo que suena claramente mas bajo = lectura, se descarta.
  3. Detecta tomas repetidas (frases que se repiten, arranques en falso) y se queda con la ULTIMA.
  4. Corta entre palabras (nunca a la mitad de una palabra), saca pausas largas.
  5. Arma una timeline NUEVA, ordenada, con marcadores para revisar. La original no se toca.

Requiere: pip install faster-whisper python-docx numpy   y ffmpeg en PATH
"""
import os, re, sys, unicodedata, subprocess, tempfile, threading, difflib, wave, hashlib, pickle
from collections import Counter
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:                                  # opcional: si copiaste gpu_runtime.py a esta carpeta, prepara CUDA
    import gpu_runtime
    gpu_runtime.preparar_cuda()
except Exception:
    pass

# ---------- Ajustes ----------
MODEL = "large-v3-turbo"
VERSION = "cortes auto v1 (manda la transcripcion)"
PRE = 0.10               # segundos que se dejan antes de la primera palabra de cada corte
POST = 0.20              # segundos que se dejan despues de la ultima palabra de cada corte
PAUSA_FRASE = 0.8        # una pausa mayor a esto separa una frase de otra
REF_VENTANA = 45.0       # segundos a cada lado para calcular tu volumen "normal" local
REF_PERCENTIL = 80       # el volumen normal = el nivel que alcanza el 20 % mas fuerte de las frases cercanas
UMBRAL_REPETIDA = 0.70   # que tan parecida tiene que ser una frase a otra para contarla como repeticion
LOOKBACK = 10            # con cuantas frases anteriores se compara para buscar repeticiones
VENTANA_T = 240.0        # segundos maximos entre una toma y su repeticion
FLAG_COBERTURA = 0.85    # si la repeticion se parece menos que esto, se marca "revisar"
MARCA_ABSOLUTA = False   # si los marcadores caen corridos (ej. 1 hora), ponelo en True
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".indienow_auto_cache")
CUSTOM = "indienow-auto"

# Colores de marcador
C_DUDA, C_DIFIERE, C_ORDEN = "Yellow", "Pink", "Blue"

# ---------- Conexion con Resolve ----------
os.environ.setdefault("RESOLVE_SCRIPT_API",
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting")
os.environ.setdefault("RESOLVE_SCRIPT_LIB",
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
sys.path.append(os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules"))
import DaVinciResolveScript as dvr

resolve = dvr.scriptapp("Resolve")
project = resolve.GetProjectManager().GetCurrentProject()
mp = project.GetMediaPool()
timeline = project.GetCurrentTimeline()
if not timeline:
    sys.exit("No hay timeline abierta en Resolve.")

FPS = float(timeline.GetSetting("timelineFrameRate"))
TL_START = timeline.GetStartFrame()
TL_NAME = timeline.GetName()


# ---------- Utilidades ----------
def norm(w):
    w = unicodedata.normalize("NFD", w.lower())
    return re.sub(r"[^a-z0-9ñ]", "", "".join(c for c in w if unicodedata.category(c) != "Mn"))


def mmss(t):
    t = max(0.0, t)
    return f"{int(t // 60)}:{int(t % 60):02d}"


def limpiar(p):
    return p.strip(" “”\"‘’¿¡().,;:…—-?!")


# ---------- Guion ----------
def leer_guion(path):
    if path.lower().endswith(".docx"):
        import docx
        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    return open(path, encoding="utf-8-sig").read()


def es_cabecera(l):
    return ("—" in l or " – " in l) and bool(re.search(r"[“\"‘]|álbum|album|EP", l))


def palabras_del_guion(texto):
    """Palabras del guion en orden, sin cabeceras: [(normalizada, como_esta_escrita)]."""
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


def formas_del_guion(G):
    """Como se escribe cada palabra en el guion (la forma mas usada)."""
    c = {}
    for n, d in G:
        f = limpiar(d)
        if f:
            c.setdefault(n, Counter())[f] += 1
    return {n: cn.most_common(1)[0][0] for n, cn in c.items()}


def nombres_del_guion(G):
    """Secuencias de palabras con mayúscula que no abren una frase (bandas, discos, nombres)."""
    out, cur = [], []
    for k, (_, d) in enumerate(G):
        ini = k == 0 or G[k - 1][1].rstrip("”\"’)").endswith((".", "?", "!", "…"))
        if d.lstrip("“\"‘¿¡(")[:1].isupper() and not ini:
            cur.append(d.strip("“”\"‘’¿¡().,;:"))
        else:
            if cur:
                out.append(" ".join(cur))
            cur = []
        if d.endswith((",", ";", ":")) and cur:
            out.append(" ".join(cur)); cur = []
    if cur:
        out.append(" ".join(cur))
    return list(dict.fromkeys(out))


def igualar_al_guion(T, G):
    """Palabras mal oidas parecidas a una del guion se igualan a ella (solo para comparar y escribir)."""
    if not G:
        return [t[0] for t in T]
    vocab = sorted({n for n, _ in G})
    vs, cache, Tn = set(vocab), {}, []
    for t in T:
        n = t[0]
        if n not in vs and len(n) >= 4:
            if n not in cache:
                m = difflib.get_close_matches(n, vocab, n=1, cutoff=0.84)
                cache[n] = m[0] if m else n
            n = cache[n]
        Tn.append(n)
    return Tn


# ---------- Cache de transcripcion ----------
def clave_cache(pista, f_ini, f_fin, prompt):
    partes = ["auto", MODEL, prompt, str(FPS), str(f_ini), str(f_fin)]
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
        with open(os.path.join(CACHE_DIR, clave + ".pkl"), "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def cache_guardar(clave, datos):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, clave + ".pkl"), "wb") as f:
            pickle.dump(datos, f)
    except Exception:
        pass


# ---------- Marcadores ----------
def poner_marca(tl, frame, color, nombre, nota, dur=1, custom=CUSTOM):
    base = tl.GetStartFrame() if MARCA_ABSOLUTA else 0
    for k in range(8):
        try:
            if tl.AddMarker(base + int(frame) + k, color, nombre, nota, max(1, int(dur)), custom):
                return True
        except Exception:
            pass
    return False


# ---------- Audio de la timeline ----------
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
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{off:.3f}", "-t", f"{dur:.3f}",
                        "-i", src, "-ac", "1", "-ar", "16000", wav], check=True)
        segs.append((wav, (a - f_ini) / FPS))
    return segs


def cargar_wav(path):
    import numpy as np
    with wave.open(path, "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


ALUCINACIONES = ["graciasporverelvideo", "graciasporver", "suscribete", "subtitulosrealizadospor",
                 "subtitulosporlacomunidad", "amaraorg", "graciasporvernos"]
_ultimos = []


def es_alucinacion(seg):
    t = norm(seg.text)
    _ultimos.append(t); del _ultimos[:-3]
    if any(b in t for b in ALUCINACIONES) or t == "gracias":
        return True
    if len(_ultimos) == 3 and t and _ultimos[0] == _ultimos[1] == _ultimos[2]:
        return True
    return seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.8


def transcribir(segs, prompt, progreso):
    """Devuelve ([(normalizada, inicio, fin, palabra_original)], envolventes_de_volumen)."""
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(MODEL, device="cuda", compute_type="int8_float16")
    except Exception:
        model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    total = sum(float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", w]).strip())
        for w, _ in segs) or 1
    import numpy as np
    hecho, palabras, envs = 0.0, [], []
    for wav, t0 in segs:
        audio = cargar_wav(wav)
        n = len(audio) // 160                      # un valor de volumen cada 10 ms
        if n:
            fr = audio[:n * 160].reshape(n, 160)
            envs.append((t0, 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-6)))
        it, info = model.transcribe(audio, language="es", word_timestamps=True,
                                    initial_prompt=prompt, vad_filter=False, beam_size=5,
                                    condition_on_previous_text=False)
        for s in it:
            progreso(35 + 45 * (hecho + s.end) / total, "Transcribiendo...")
            if es_alucinacion(s):
                continue
            for w in s.words or []:
                n = norm(w.word)
                if n:
                    palabras.append((n, t0 + w.start, t0 + w.end, w.word.strip()))
        hecho += info.duration
    return palabras, envs


def refinar(T, envs):
    """Ajusta inicio/fin de cada palabra al sonido real (Whisper estira palabras sobre los silencios)."""
    import numpy as np, math
    if not envs:
        return T
    umbral = np.percentile(np.concatenate([e for _, e in envs]), 10) + 12
    out = []
    for n, s, e, raw in T:
        env = next(((t0, ev) for t0, ev in envs if t0 - 0.001 <= s < t0 + len(ev) * 0.01), None)
        if env is None:
            out.append((n, s, e, raw)); continue
        t0, ev = env
        a, b = max(0, int((s - t0) / 0.01)), min(len(ev), int(math.ceil((e - t0) / 0.01)))
        if b - a < 2:
            out.append((n, s, e, raw)); continue
        v = ev[a:b] > umbral
        runs, k = [], 0
        while k < len(v):
            if v[k]:
                m = k
                while m < len(v) and v[m]:
                    m += 1
                runs.append([k, m]); k = m
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
            out.append((n, s, e, raw)); continue
        r = max(unidos, key=lambda r: r[1] - r[0])
        out.append((n, t0 + (a + r[0]) * 0.01, t0 + (a + r[1]) * 0.01, raw))
    return [(n, s, min(e, s + 1.5), raw) for n, s, e, raw in out]


def niveles(T, envs):
    """Volumen (dB) de cada palabra, medido en el audio real del microfono."""
    import numpy as np
    if not envs:
        return None
    out = []
    for t in T:
        s, e = t[1], t[2]
        env = next(((t0, ev) for t0, ev in envs if t0 - 0.001 <= s < t0 + len(ev) * 0.01), None)
        if env is None:
            out.append(float("nan")); continue
        t0, ev = env
        a = max(0, int((s - t0) / 0.01))
        b = min(len(ev), max(a + 1, int((e - t0) / 0.01)))
        out.append(float(np.percentile(ev[a:b], 90)))
    arr = np.array(out)
    med = float(np.nanmedian(arr)) if np.isfinite(arr).any() else 0.0
    return [med if not np.isfinite(x) else x for x in out]


# ---------- Frases, lecturas, tomas ----------
def dividir_en_frases(T):
    utts, cur = [], []
    for k in range(len(T)):
        if cur and T[k][1] - T[cur[-1]][2] > PAUSA_FRASE:
            utts.append(cur); cur = []
        cur.append(k)
    if cur:
        utts.append(cur)
    return utts


def ubicar(ws, Gn, indice):
    """Donde del guion cae mejor esta frase. Devuelve (posicion, cobertura 0-1)."""
    n = len(ws)
    if n < 2 or not Gn:
        return None, 0.0
    cuenta = Counter()
    for k, w in enumerate(ws):
        if len(w) >= 4:
            for p in indice.get(w, ()):
                cuenta[max(0, p - k)] += 1
    mejor, mejor_s = None, 0.0
    for s, _ in cuenta.most_common(8):
        sm = difflib.SequenceMatcher(None, ws, Gn[s:s + n + 4], autojunk=False)
        cob = sum(b.size for b in sm.get_matching_blocks()) / n
        if cob > mejor_s:
            mejor, mejor_s = s, cob
    return mejor, mejor_s


def referencias(infos):
    """Volumen 'normal' local: se adapta si el microfono se acerca o se aleja."""
    import numpy as np
    niv = np.array([u["nivel"] for u in infos])
    tm = np.array([u["t"] for u in infos])
    glob = float(np.percentile(niv, REF_PERCENTIL))
    for u in infos:
        m = np.abs(tm - u["t"]) <= REF_VENTANA
        u["ref"] = float(np.percentile(niv[m], REF_PERCENTIL)) if m.sum() >= 4 else glob


PALABRAS_TRABADAS = {"por", "que", "de", "la", "el", "en", "y", "a", "con", "los", "las", "un", "una",
                     "se", "es", "lo", "del", "al", "para", "su", "mi", "o", "e"}


def _igual(a, b):
    """Dos palabras iguales, o casi iguales si son largas (semana / semanal)."""
    if a == b:
        return True
    return len(a) >= 5 and len(b) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def sin_reinicios(idx, Tn, T):
    """Dentro de una frase saca los intentos viejos:
       - trabadas: una palabra de enlace dicha dos veces seguidas ('por por qué')
       - reinicios: arranca, se traba y vuelve a empezar (3 palabras iguales, o 2 palabras largas
         iguales si hubo una duda/pausa en el medio).
       Devuelve (indices_que_quedan, [lo_que_se_quito])."""
    res, quitadas, k, n = [], [], 0, len(idx)
    while k < n:
        w = Tn[idx[k]]
        if k + 1 < n and w == Tn[idx[k + 1]] and w in PALABRAS_TRABADAS:
            quitadas.append([idx[k]]); k += 1
            continue
        salto = None
        for m in range(k + 1, min(n, k + 13)):
            if m + 3 <= n and k + 3 <= n and all(_igual(Tn[idx[k + j]], Tn[idx[m + j]]) for j in range(3)):
                salto = m
                break
            if m + 2 <= n and k + 2 <= n and all(
                    _igual(Tn[idx[k + j]], Tn[idx[m + j]]) and len(Tn[idx[k + j]]) >= 4 for j in range(2)):
                if any(T[idx[j + 1]][1] - T[idx[j]][2] >= 0.25 for j in range(k, m)):
                    salto = m
                    break
        if salto is not None:
            quitadas.append(idx[k:salto]); k = salto
        else:
            res.append(idx[k]); k += 1
    return res, quitadas


def solapan(a, b):
    """(cobertura sobre la mas corta, palabras en comun) entre dos listas de palabras."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    m = sum(x.size for x in sm.get_matching_blocks())
    return m / max(1, min(len(a), len(b))), m


def cortes_de(T, idxs, pausa):
    """Cortes (segundos) de una toma. Siempre entre palabras, nunca a la mitad de una."""
    segs, cur = [], [idxs[0]]
    for a, b in zip(idxs, idxs[1:]):
        if b != a + 1 or T[b][1] - T[a][2] > pausa:
            segs.append(cur); cur = [b]
        else:
            cur.append(b)
    segs.append(cur)
    out = []
    for sg in segs:
        a, b = sg[0], sg[-1]
        ini = T[a][1] - PRE
        if a > 0:
            ini = max(ini, (T[a - 1][2] + T[a][1]) / 2)
        fin = T[b][2] + POST
        if b + 1 < len(T):
            fin = min(fin, (T[b][2] + T[b + 1][1]) / 2)
        ini = max(0.0, ini)
        if fin > ini:
            out.append((ini, fin))
    return out


# ---------- Armar la timeline nueva ----------
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
    exacta = buscar(mp.GetRootFolder())
    return exacta or (por_nombre[0] if por_nombre else None)


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
            # sin recordFrame: Resolve los agrega uno detrás del otro, pegados, sin huecos
            out.append({"mediaPoolItem": mpi, "startFrame": sf, "endFrame": sf + n - 1,
                        "mediaType": 1 if tipo == "video" else 2, "trackIndex": destino})
        acum += b - a
    return out


def pos_en_nueva(cortes_f, frame_orig):
    acum = 0
    for a, b in cortes_f:
        if a <= frame_orig < b:
            return acum + (frame_orig - a)
        acum += b - a
    return None


def revisar_huecos(tl):
    """Cuenta huecos entre clips de V1 y A1 de la timeline nueva y compara donde termina cada pista."""
    res, fines = [], {}
    for tipo in ("video", "audio"):
        try:
            items = sorted(tl.GetItemListInTrack(tipo, 1) or [], key=lambda it: it.GetStart())
        except Exception:
            continue
        huecos = []
        for a, b in zip(items, items[1:]):
            d = b.GetStart() - a.GetEnd()
            if d > 0:
                huecos.append(d)
        if items:
            fines[tipo] = items[-1].GetEnd()
        if huecos:
            res.append(f"{tipo}: {len(huecos)} huecos (frames: {huecos[:8]})")
    if len(fines) == 2 and fines["video"] != fines["audio"]:
        res.append(f"video y audio terminan con {abs(fines['video'] - fines['audio'])} frames de diferencia")
    return res


def construir(cortes_f, pista_audio, pista_video, otras):
    nombre, n = f"{TL_NAME} - auto", 1
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
                extras.append((dest, info)); dest += 1
    ok_v = (not v) or bool(mp.AppendToTimeline(v))
    ok_a = (not a) or bool(mp.AppendToTimeline(a))
    for d, info in extras:
        ok_a = bool(mp.AppendToTimeline(info)) and ok_a
        try:
            nueva.SetTrackEnable("audio", d, False)
        except Exception:
            pass
    return nueva, ok_v, ok_a, len(v), len(a), len(extras)


# ---------- Proceso principal ----------
def correr(cfg, progreso, reporte):
    import numpy as np
    progreso(2, "Leyendo guion...")
    G = palabras_del_guion(leer_guion(cfg["guion"])) if cfg["guion"] else []
    Gn = [n for n, _ in G]
    indice = {}
    for p, n in enumerate(Gn):
        indice.setdefault(n, []).append(p)
    formas = formas_del_guion(G)

    mi = timeline.GetMarkInOut() or {}
    ai = mi.get("audio") or mi.get("video") or {}
    if cfg["rango"] == "inout" and ai:
        f_ini, f_fin = ai["in"], ai["out"]
    else:
        f_ini, f_fin = TL_START, timeline.GetEndFrame()

    prompt = ""
    if G:
        nombres = nombres_del_guion(G)
        cab = ("Nombres: " + ", ".join(nombres) + ". ") if nombres else ""
        prompt = (cab[:300] + " ".join(d for _, d in G))[:600]
    clave = clave_cache(cfg["pista"], f_ini, f_fin, prompt)
    datos = cache_leer(clave) if cfg["cache"] else None
    if datos:
        T, envs = datos
        progreso(80, "Usando la transcripción guardada...")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            progreso(5, "Extrayendo audio del micrófono...")
            segs = segmentos_audio(cfg["pista"], f_ini, f_fin, tmp)
            if not segs:
                raise RuntimeError("No hay audio en esa pista/rango.")
            progreso(30, "Cargando modelo...")
            T, envs = transcribir(segs, prompt, progreso)
        if T:
            cache_guardar(clave, (T, envs))
    if not T:
        raise RuntimeError("No se transcribió nada.")
    T = refinar(T, envs)
    Tn = igualar_al_guion(T, G)
    niv = niveles(T, envs)

    progreso(82, "Analizando frases, volumen y tomas repetidas...")
    utts = dividir_en_frases(T)
    infos = []
    for idx in utts:
        ws = [Tn[k] for k in idx]
        pos, cob = ubicar(ws, Gn, indice)
        infos.append({"idx": idx, "t": (T[idx[0]][1] + T[idx[-1]][2]) / 2,
                      "nivel": float(np.median([niv[k] for k in idx])) if niv else 0.0,
                      "gpos": pos, "gs": cob})
    usar_volumen = bool(niv) and cfg["bajada"] > 0
    if infos:
        referencias(infos)

    # ---- lecturas (volumen mas bajo que tu volumen normal de ese momento)
    lecturas = []
    for u in infos:
        u["caida"] = u["ref"] - u["nivel"] if usar_volumen else 0.0
        n = len(u["idx"])
        u["lectura"] = bool(usar_volumen and n >= 2 and (
            u["caida"] >= cfg["bajada"] or
            (u["caida"] >= cfg["bajada"] * 0.6 and u["gs"] >= 0.9 and n >= 4)))
        if u["lectura"]:
            lecturas.append(u)

    # ---- tomas repetidas: se queda la ultima
    grupos = []
    for u in infos:
        if u["lectura"]:
            continue
        idx, quit_ = sin_reinicios(u["idx"], Tn, T)
        if not idx:
            continue
        flags_u = []
        if quit_:
            txt_q = " | ".join(" ".join(formas.get(Tn[k]) or limpiar(T[k][3]) for k in q) for q in quit_)
            flags_u.append((C_DUDA, "REINICIO DENTRO DE LA FRASE",
                            "Saqué un intento viejo de esta frase: " + txt_q[:200]))
        ws = [Tn[k] for k in idx]
        mejor = None
        for gi in range(len(grupos) - 1, max(-1, len(grupos) - 1 - LOOKBACK), -1):
            g = grupos[gi]
            if T[idx[0]][1] - T[g["idx"][-1]][2] > VENTANA_T:
                continue
            cob, m = solapan(ws, [Tn[k] for k in g["idx"]])
            if m >= 2 and cob >= UMBRAL_REPETIDA and (mejor is None or cob > mejor[0]):
                mejor = (cob, gi)
        if mejor:
            g = grupos[mejor[1]]
            antes = len(g["idx"])
            g["tomas"] += 1
            g["idx"], g["u"] = idx, u
            g["flags"] = list(flags_u)
            if len(idx) < 0.6 * antes:
                g["flags"].append((C_DUDA, "ÚLTIMA TOMA MÁS CORTA",
                                   f"Usé la última de {g['tomas']} tomas, pero es bastante más corta que la anterior."))
            elif mejor[0] < FLAG_COBERTURA:
                g["flags"].append((C_DUDA, "TOMAS DISTINTAS",
                                   f"Usé la última de {g['tomas']} tomas, pero no son idénticas. Revisá."))
        else:
            grupos.append({"idx": idx, "u": u, "tomas": 1, "flags": list(flags_u)})
    if not grupos:
        raise RuntimeError("No quedó ninguna toma válida. Probá bajar el ajuste de volumen.")

    # ---- orden y presencia en el guion (solo marcadores, no cambia el orden de los cortes)
    maxp = -1
    for g in grupos:
        u = g["u"]
        if G and u["gpos"] is not None and u["gs"] >= 0.5:
            if u["gpos"] + 30 < maxp:
                g["flags"].append((C_ORDEN, "FUERA DE ORDEN",
                                   "Esta frase está ANTES en el guion de lo que ya se dijo. Revisá el orden."))
            maxp = max(maxp, u["gpos"] + len(g["idx"]))
        elif G and u["gs"] < 0.35 and len(g["idx"]) >= 4:
            g["flags"].append((C_DIFIERE, "NO ESTÁ EN EL GUION",
                               "Se dijo algo que no se parece al guion (improvisado o cambiado)."))

    # ---- cortes
    por_grupo, cortes = [], []
    for g in grupos:
        cs = cortes_de(T, g["idx"], cfg["pausa"])
        por_grupo.append(cs)
        cortes += cs
    unidos = []
    for a, b in cortes:
        if unidos and -0.02 <= a - unidos[-1][1] <= 0.15:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], b))
        else:
            unidos.append((a, b))
    cortes_f = []
    for a, b in unidos:
        fa, fb = f_ini + round(a * FPS), f_ini + round(b * FPS)
        fa, fb = max(f_ini, fa), min(f_fin, fb)
        if fb > fa:
            cortes_f.append((fa, fb))

    progreso(90, "Armando la timeline nueva...")
    nueva, ok_v, ok_a, nv, na, ne = construir(cortes_f, cfg["pista"], cfg["video"], cfg["otras"])

    # ---- marcadores
    progreso(96, "Poniendo marcadores...")
    cuenta, fallos = Counter(), 0
    pos_grupo = []
    for g, cs in zip(grupos, por_grupo):
        pos = pos_en_nueva(cortes_f, f_ini + round(cs[0][0] * FPS) + 1) if cs else None
        pos_grupo.append(pos)
        for color, nombre, nota in g["flags"]:
            if pos is not None and poner_marca(nueva, pos, color, nombre, nota):
                cuenta[color] += 1
            else:
                fallos += 1

    # ---- informe
    final_idx = [k for g in grupos for k in g["idx"]]
    final_n = [Tn[k] for k in final_idx]
    rep = [VERSION]
    n_rep = sum(g["tomas"] - 1 for g in grupos)
    rep.append(f"{len(infos)} frases: {len(lecturas)} descartadas por ser lectura (volumen bajo), "
               f"{n_rep} descartadas por ser tomas repetidas. {len(grupos)} frases en la timeline.")
    if usar_volumen and infos:
        rep.append(f"Volumen normal medido: entre {min(u['ref'] for u in infos):.0f} y {max(u['ref'] for u in infos):.0f} dB "
                   f"(se descarta lo que está {cfg['bajada']:.0f} dB o más por debajo de lo normal del momento).")
    if lecturas:
        lugares = []
        for u in sorted(lecturas, key=lambda x: x["t"]):
            if not lugares or u["t"] - lugares[-1] > 8:
                lugares.append(u["t"])
        rep.append("Lecturas descartadas cerca de: " + ", ".join(mmss(t) for t in lugares[:20]) + ".")
    faltas = []
    if G:
        sm = difflib.SequenceMatcher(None, Gn, final_n, autojunk=False)
        ok = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                ok += i2 - i1
            elif tag in ("delete", "replace") and i2 - i1 >= 4:
                faltas.append(" ".join(G[k][1] for k in range(i1, i2)))
        rep.append(f"{ok} de {len(G)} palabras del guion están en la timeline, en orden ({100 * ok / len(G):.0f} %).")
        if faltas:
            rep.append("Partes del guion que no aparecen (o se dijeron muy distinto):")
            rep += ["  - " + f[:110] for f in faltas[:12]]
            if len(faltas) > 12:
                rep.append(f"  ... y {len(faltas) - 12} más (están en el log).")
    rep.append(f"Marcadores: amarillo {cuenta[C_DUDA]} (revisar tomas), rosa {cuenta[C_DIFIERE]} (no está en el guion), "
               f"azul {cuenta[C_ORDEN]} (fuera de orden)" + (f". {fallos} no se pudieron poner." if fallos else "."))
    rep.append(f"Timeline creada: {nueva.GetName()} ({nv} trozos de video, {na} de audio" +
               (f", {ne} pistas extra desactivadas)." if ne else ")."))
    try:
        huecos = revisar_huecos(nueva)
        rep.append("Huecos entre clips: " + ("; ".join(huecos) if huecos else "ninguno (todo pegado)."))
    except Exception as ex:
        rep.append("No pude revisar los huecos: " + str(ex))
    if nv == 0:
        rep.append("OJO: no encontré video en esa pista de video.")
    if not (ok_v and ok_a):
        rep.append("OJO: Resolve rechazó parte de los clips. Revisá la timeline.")

    # ---- log completo con la transcripcion corregida (junto al guion)
    try:
        carpeta = os.path.dirname(cfg["guion"]) if cfg["guion"] else os.path.expanduser("~")
        ruta = os.path.join(carpeta, TL_NAME + "_auto_log.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("\n".join(rep) + "\n")
            if faltas:
                f.write("\n=== PARTES DEL GUION QUE NO APARECEN ===\n" + "\n".join("- " + x for x in faltas) + "\n")
            f.write("\n=== LECTURAS DESCARTADAS (posición en la original, caída de volumen) ===\n")
            for u in sorted(lecturas, key=lambda x: x["t"]):
                txt = " ".join(formas.get(Tn[k]) or limpiar(T[k][3]) for k in u["idx"])
                f.write(f"{mmss(u['t']):>6}  -{u['caida']:.0f} dB  {txt[:120]}\n")
            f.write("\n=== TRANSCRIPCIÓN FINAL, CORREGIDA CON EL GUION (tiempo en la timeline nueva) ===\n")
            for g, pos in zip(grupos, pos_grupo):
                txt = " ".join(formas.get(Tn[k]) or limpiar(T[k][3]) for k in g["idx"])
                marca = mmss(pos / FPS) if pos is not None else "  ?  "
                extra = f"  [{g['tomas']} tomas]" if g["tomas"] > 1 else ""
                f.write(f"{marca:>6}  {txt}{extra}\n")
        rep.append("\nLog y transcripción: " + ruta)
    except Exception as ex:
        rep.append("No pude guardar el log: " + str(ex))
    reporte(rep)
    progreso(100, "Listo")


# ---------- Ventana ----------
def main():
    n_audio = timeline.GetTrackCount("audio")
    n_video = timeline.GetTrackCount("video")
    root = tk.Tk(); root.title("Indie Now - " + VERSION); root.geometry("470x720")
    v_guion = tk.StringVar(); v_pista = tk.StringVar(value="A1"); v_video = tk.StringVar(value="V1")
    v_rango = tk.StringVar(value="inout"); v_otras = tk.BooleanVar(value=False)
    v_baja = tk.DoubleVar(value=7); v_pausa = tk.StringVar(value="0.5"); v_cache = tk.BooleanVar(value=True)

    def elegir():
        p = filedialog.askopenfilename(filetypes=[("Guion", "*.txt *.docx")])
        if p:
            v_guion.set(p)

    ttk.Label(root, text="Timeline: " + TL_NAME, wraplength=440).pack(anchor="w", padx=12, pady=(12, 0))
    ttk.Button(root, text="Elegir guion (opcional, solo para corregir y revisar)...",
               command=elegir).pack(fill="x", padx=12, pady=(8, 0))
    ttk.Label(root, textvariable=v_guion, wraplength=440).pack(anchor="w", padx=12)
    ttk.Label(root, text="Video (iPhone)").pack(anchor="w", padx=12, pady=(8, 0))
    ttk.Combobox(root, textvariable=v_video, state="readonly",
                 values=[f"V{i}" for i in range(1, n_video + 1)]).pack(fill="x", padx=12)
    ttk.Label(root, text="Audio del MICRÓFONO (de acá se transcribe y se copia el sonido)").pack(anchor="w", padx=12, pady=(8, 0))
    ttk.Combobox(root, textvariable=v_pista, state="readonly",
                 values=[f"A{i}" for i in range(1, n_audio + 1)]).pack(fill="x", padx=12)
    ttk.Checkbutton(root, text="Copiar también las otras pistas de audio (quedan desactivadas)",
                    variable=v_otras).pack(anchor="w", padx=12, pady=(4, 0))
    ttk.Radiobutton(root, text="Puntos In / Out", variable=v_rango, value="inout").pack(anchor="w", padx=12, pady=(8, 0))
    ttk.Radiobutton(root, text="Línea completa", variable=v_rango, value="full").pack(anchor="w", padx=12)
    fila = ttk.Frame(root); fila.pack(fill="x", padx=12, pady=(8, 0))
    ttk.Label(fila, text="Sacar pausas de más de").pack(side="left")
    ttk.Entry(fila, textvariable=v_pausa, width=5).pack(side="left", padx=4)
    ttk.Label(fila, text="segundos").pack(side="left")
    ttk.Label(root, text="Descartar lecturas: frases más bajas que tu volumen normal por X dB.\n"
                         "Más bajo = descarta más. 0 = no usar.", wraplength=440).pack(anchor="w", padx=12, pady=(8, 0))
    tk.Scale(root, from_=0, to=20, orient="horizontal", variable=v_baja).pack(fill="x", padx=12)
    ttk.Checkbutton(root, text="Usar transcripción guardada si el audio no cambió (más rápido)",
                    variable=v_cache).pack(anchor="w", padx=12, pady=(8, 0))
    barra = ttk.Progressbar(root, maximum=100); barra.pack(fill="x", padx=12, pady=(12, 0))
    estado = ttk.Label(root, text="", wraplength=440); estado.pack(anchor="w", padx=12)
    caja = tk.Text(root, height=12, wrap="word", state="disabled"); caja.pack(fill="both", expand=True, padx=12, pady=(4, 0))

    def progreso(p, msg):
        root.after(0, lambda: (barra.configure(value=p), estado.configure(text=msg)))

    def reporte(lineas):
        def poner():
            caja.configure(state="normal"); caja.delete("1.0", "end")
            caja.insert("end", "\n".join(lineas)); caja.configure(state="disabled")
        root.after(0, poner)

    def go():
        try:
            pausa = float(v_pausa.get().replace(",", "."))
        except ValueError:
            return messagebox.showwarning("Pausa", "Poné un número, por ejemplo 0.5")
        cfg = {"guion": v_guion.get(), "pista": int(v_pista.get()[1:]), "video": int(v_video.get()[1:]),
               "otras": v_otras.get(), "bajada": float(v_baja.get()), "rango": v_rango.get(),
               "pausa": pausa, "cache": v_cache.get()}

        def t():
            try:
                correr(cfg, progreso, reporte)
            except Exception as ex:
                import traceback; traceback.print_exc()
                progreso(0, "Error: " + str(ex))
        threading.Thread(target=t, daemon=True).start()

    ttk.Button(root, text="Cortar", command=go).pack(fill="x", padx=12, pady=12)
    root.mainloop()


if __name__ == "__main__":
    main()
