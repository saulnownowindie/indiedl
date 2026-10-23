"""Indie Now DL - descargador para Windows con integración de navegador."""
import json, os, queue, re, shutil, subprocess, sys, threading, time, traceback, tempfile
from pathlib import Path
from urllib.parse import unquote, parse_qsl

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "IndieDL"
CFG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "indiedl.log"
TEMP_DIR = APP_DIR / "tmp"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

try:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(TEMP_DIR)
    os.environ["TMP"] = str(TEMP_DIR)
    tempfile.tempdir = str(TEMP_DIR)
    os.chdir(str(APP_DIR))
except OSError as exc:
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as _log_file:
            _log_file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + f"No se pudo preparar TEMP de IndieDL: {exc!r}\n")
    except Exception:
        pass

# ---- Ajustes de calidad ----
VIDEO_FORMAT = "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/bv*+ba/b"
AUDIO_CODEC = "mp3"
AUDIO_QUALITY = "320"
STAGES = ["Descargando", "Procesando", "Guardando archivo", "Finalizando"]
UPDATE_EVERY_DAYS = 1

DEFAULTS = {
    "last_dir": "E:\\" if os.path.isdir("E:\\") else str(Path.home() / "Videos"),
    "ask_folder": True,
    "close_when_done": False,
    "cookies_browser": "auto",
    "last_update": 0,
    "video_q": "Mejor",
    "audio_fmt": "mp3",
    "pcm_resolve": False,
    "history": [],
}

URI_RE = re.compile(r'(?i)^ytdl:(?://)?(video|audio|image)/?\?u=(.+)$')
ALLOWED = re.compile(
    r'^https://([a-z0-9-]+\.)?('
    r'youtube\.com|youtu\.be|instagram\.com|tiktok\.com|'
    r'x\.com|twitter\.com|t\.co|'
    r'pinterest\.(com|es|co\.uk|de|fr|mx|ar|cl|it|pt|jp|ca|au|nz|ie|ru)|pin\.it'
    r')/', re.I)

def log(msg):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5 * 1024 * 1024:
            try:
                LOG_FILE.replace(LOG_FILE.with_suffix(".log.old"))
            except OSError:
                pass
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass

def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        saved = json.loads(CFG_FILE.read_text(encoding="utf-8"))
        cfg.update(saved)
    except Exception:
        saved = {}
    if os.name == "nt":
        if not saved.get("mp4_default_v3"):
            cfg["pcm_resolve"] = False
        cfg["mp4_default_v3"] = True
        if saved.get("audio_fmt") == "wav":
            cfg["audio_fmt"] = "mp3"
        if saved.get("close_when_done") is True:
            cfg["close_when_done"] = False
    return cfg

def save_cfg(cfg):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CFG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"save_cfg: {e}")

def clean_url(u):
    u = u.strip()
    u = re.sub(r'(instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/[\w-]+/).*$', r'\1', u)
    u = re.sub(r'^(https://(?:www\.)?(?:x|twitter)\.com/\w+/status/\d+).*$', r'\1', u)
    return u if ALLOWED.match(u) else None

CLIP_RE = re.compile(r'&(s|e)=(\d+)(?=&|$)')

def parse_clip(uri):
    found = {k: int(v) for k, v in CLIP_RE.findall(uri.strip().strip('"').strip("'"))}
    if "s" in found and "e" in found and found["e"] > found["s"]:
        return found["s"], found["e"]
    return None

def fmt_hms(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"

def parse_uri(uri):
    raw = uri.strip().strip('"').strip("'")
    raw = CLIP_RE.sub("", raw)
    m = URI_RE.match(raw)
    if m:
        return m.group(1).lower(), clean_url(unquote(m.group(2))) or ""
    return None

BATCH_RE = re.compile(r'(?i)^ytdl:(?://)?batch/?\?(.+)$')
MAX_BATCH = 30

def parse_batch(uri):
    raw = uri.strip().strip('"').strip("'")
    m = BATCH_RE.match(raw)
    if not m:
        return None
    items, seen = [], set()
    for k, v in parse_qsl(m.group(1), keep_blank_values=True):
        if k == "u":
            u = clean_url(v)
            if u and u not in seen:
                seen.add(u)
                items.append({"url": u, "title": ""})
        elif k == "t" and items and not items[-1]["title"]:
            items[-1]["title"] = v.strip()[:120]
    return items[:MAX_BATCH] or None

class ForwardQ:
    def __init__(self, real):
        self.real = real
        self.final = None

    def put(self, ev):
        if ev and ev[0] in ("done", "err"):
            self.final = ev
        else:
            self.real.put(ev)

def register():
    if os.name != "nt":
        return
    import winreg
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    pyw = pyw if pyw.exists() else exe
    cmd = f'"{pyw}" "{Path(__file__).resolve()}" "%1"'
    base = r"Software\Classes\ytdl"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:ytdl Protocol")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)

def parse_timestamp(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        parts = value.split(":")
        if len(parts) > 3 or any(not part.isdigit() for part in parts):
            return None
        nums = [int(x) for x in parts]
        if len(nums) == 1:
            return nums[0]
        if any(n >= 60 for n in nums[1:]):
            return None
        total = 0
        for n in nums:
            total = total * 60 + n
        return total
    except (ValueError, TypeError):
        return None

def maybe_update_ytdlp(cfg, q, force=False):
    if not force and time.time() - float(cfg.get("last_update", 0) or 0) < UPDATE_EVERY_DAYS * 86400:
        return True
    q.put(("log", "Actualizando yt-dlp (nightly + dependencias web)..."))
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "--pre", "yt-dlp[default,curl-cffi]", "-q"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=NO_WINDOW, timeout=240, check=False)
        if proc.returncode == 0:
            cfg["last_update"] = time.time()
            save_cfg(cfg)
            log("yt-dlp nightly actualizado correctamente")
            q.put(("log", "yt-dlp actualizado correctamente"))
            return True
        detail = (proc.stderr or proc.stdout or "sin detalle")[-700:]
        log(f"update yt-dlp falló ({proc.returncode}): {detail}")
        q.put(("log", "No se pudo actualizar yt-dlp; se intentará con la versión instalada"))
        return False
    except Exception as e:
        log(f"update yt-dlp: {e!r}")
        q.put(("log", "Falló la actualización de yt-dlp; se usará la versión instalada"))
        return False

def ffmpeg_path():
    # 1) FFmpeg disponible en PATH.
    p = shutil.which("ffmpeg")
    if p:
        return p

    # 2) Copias locales que puede incluir el instalador de IndieDL.
    candidates = [
        APP_DIR / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
        APP_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
        Path(sys.executable).resolve().parent / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    # 3) Binario distribuido por imageio-ffmpeg dentro del entorno virtual.
    try:
        import imageio_ffmpeg
        binary = imageio_ffmpeg.get_ffmpeg_exe()
        if binary and os.path.isfile(binary):
            return binary
    except Exception as exc:
        log(f"imageio-ffmpeg no disponible: {exc!r}")
    return None

def vfmt(q):
    h = {"1080p": 1080, "720p": 720}.get(q)
    if not h:
        return ("bv*[vcodec^=avc1][dynamic_range=SDR]+ba[acodec^=mp4a]/"
                "bv*[dynamic_range=SDR]+ba/b[ext=mp4]/bv*+ba/b")
    return (f"bv*[height<={h}][vcodec^=avc1][dynamic_range=SDR]+ba[acodec^=mp4a]/"
            f"bv*[height<={h}][dynamic_range=SDR]+ba/b[height<={h}]")

def fb(n):
    if not n:
        return "-"
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024

def ft(sec):
    if sec is None:
        return "-"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"

def probe(ff, path):
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True,
                           creationflags=NO_WINDOW, timeout=60)
        return (r.stderr or "") + (r.stdout or "")
    except Exception as e:
        return str(e)

def audio_is_safe(info):
    if sum(1 for l in info.splitlines() if "audio:" in l.lower() and "stream #" in l.lower()) > 1:
        return False
    for line in info.splitlines():
        low = line.lower()
        if "audio:" not in low:
            continue
        if "aac" not in low and "mp4a" not in low:
            return False
        if "he-aac" in low or "he_aac" in low or "aac (he" in low:
            return False
        if "aac (main" in low:
            return False
        m = re.search(r"(\d+) hz", low)
        if m and int(m.group(1)) not in (44100, 48000):
            return False
        if not ("mono" in low or "stereo" in low):
            return False
        return True
    return True

def ensure_mp4_aac(ff, src, q):
    if not src or not os.path.isfile(src):
        return src
    info = probe(ff, src)
    if "Audio:" not in info:
        q.put(("log", "ATENCION: el archivo descargado NO trae pista de audio"))
        return src
    is_mp4 = os.path.splitext(src)[1].lower() == ".mp4"
    if is_mp4 and audio_is_safe(info):
        q.put(("log", "MP4 intacto: audio AAC estándar, no se modificó nada"))
        return src

    base = os.path.splitext(src)[0]
    dst = base + ".indiedl_tmp.mp4"
    final = base + ".mp4"
    cmd = [ff, "-y", "-i", src, "-map", "0:v:0?", "-map", "0:a:0",
           "-c:v", "copy",
           "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "256k", "-ar", "48000",
           "-map_metadata", "0",
           "-movflags", "+faststart", dst]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=900)
    except Exception as e:
        q.put(("log", "No pude normalizar el audio: " + str(e)))
        return src
    
    def safe_replace(src_path, dst_path):
        for _ in range(5):
            try:
                os.replace(src_path, dst_path)
                return True
            except PermissionError:
                time.sleep(1)
        return False

    if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
        before, after = audio_level(ff, src), audio_level(ff, dst)
        def _sound(lv):
            return lv is not None and lv[1] != float("-inf") and lv[1] > -60
        if _sound(before) and not _sound(after):
            q.put(("log", "La conversión dejó el audio peor: se conserva el archivo original"))
            q.put(("note", "No se pudo corregir el audio automáticamente; se dejó el original."))
            try: os.remove(dst)
            except Exception: pass
            return src
        if safe_replace(dst, final):
            if os.path.abspath(final) != os.path.abspath(src):
                try: os.remove(src)
                except Exception: pass
            q.put(("log", "MP4: video copiado sin cambios; audio convertido a AAC-LC estándar"))
            q.put(("note", "Audio corregido automáticamente (AAC estándar) para que lo lea DaVinci."))
            return final
    try:
        if os.path.exists(dst):
            os.remove(dst)
    except Exception:
        pass
    q.put(("log", "No pude normalizar el audio (se deja el original): " + (r.stderr or "")[-160:].strip()))
    return src

def audio_level(ff, path):
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", path, "-map", "0:a:0", "-af", "volumedetect",
                            "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW, timeout=300)
        t = (r.stderr or "") + (r.stdout or "")
        m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", t)
        k = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", t)
        if not (m and k):
            return None
        f = lambda x: float("-inf") if x == "-inf" else float(x)
        return f(m.group(1)), f(k.group(1))
    except Exception:
        return None

def report_audio(ff, path, q):
    if "Audio:" not in probe(ff, path):
        q.put(("log", "ATENCION: el archivo final NO trae pista de audio"))
        q.put(("note", "OJO: el video no trae audio."))
        return
    lv = audio_level(ff, path)
    if lv is None:
        q.put(("log", "ATENCION: no pude medir el audio (puede estar dañado)"))
        q.put(("note", "OJO: no pude comprobar el audio; revísalo antes de editar."))
    elif lv[1] == float("-inf") or (lv[1] < -60 and lv[0] < -70):
        q.put(("log", "ATENCION: el audio descargado está en SILENCIO (la fuente lo trajo mudo)"))
        q.put(("note", "OJO: el audio quedó en SILENCIO. La fuente lo trajo mudo; prueba otro enlace o fuente."))
    else:
        q.put(("log", f"Audio verificado: suena (pico {lv[1]:.1f} dB)"))

def safe_media_name(path, q):
    import unicodedata
    d, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    keep = []
    for ch in stem:
        cat = unicodedata.category(ch)
        if ord(ch) > 0xFFFF or ch in "\ufe0e\ufe0f" or cat[0] == "C" or cat in ("So", "Sk"):
            continue
        keep.append(ch)
    clean = re.sub(r"\s+", " ", "".join(keep)).strip(" .") or "video"
    if clean == stem:
        return path
    new, n = os.path.join(d, clean + ext), 1
    while os.path.exists(new):
        n += 1
        new = os.path.join(d, f"{clean} ({n}){ext}")
    try:
        os.rename(path, new)
        q.put(("log", "Nombre limpiado (sin emojis/símbolos) para que DaVinci no lo marque offline"))
        return new
    except OSError as e:
        q.put(("log", f"No pude renombrar el archivo: {e}"))
        return path

def video_needs_h264(info):
    line = next((l for l in info.splitlines()
                 if "Stream #" in l and "Video:" in l and "attached pic" not in l), None)
    if not line:
        return None
    m = re.search(r"Video:\s*([a-z0-9_]+)", line, re.I)
    codec = (m.group(1) if m else "").lower()
    if codec != "h264":
        return f"códec {codec or 'desconocido'}"
    pm = re.search(r"\b(yuvj?4\d\dp\w*|gbrp\w*|nv\d+|p0\d+\w*|rgb\w*|bgr\w*)\b", line)
    if pm and pm.group(1) not in ("yuv420p", "yuvj420p"):
        return f"formato de píxel {pm.group(1)}"
    f = re.search(r"([\d.]+)\s*fps", line)
    t = re.search(r"([\d.]+)(k?)\s*tbr", line)
    if f and t:
        fps = float(f.group(1))
        tbr = float(t.group(1)) * (1000 if t.group(2) else 1)
        if tbr and abs(fps - tbr) / tbr > 0.02:
            return f"cuadros variables ({fps:g} fps vs {tbr:g} tbr)"
    return None

def ensure_h264(ff, src, q):
    if not src or not os.path.isfile(src):
        return src
    why = video_needs_h264(probe(ff, src))
    if not why:
        return src
    q.put(("stage", 2, "Convirtiendo video a H.264"))
    q.put(("log", f"Video no seguro para DaVinci ({why}): intentando conversión H.264 por GPU; si no está disponible, se usará CPU"))
    base = os.path.splitext(src)[0]
    dst, final = base + ".indiedl_h264.mp4", base + ".mp4"
    err = ""
    encoders = [
        ("h264_nvenc", ["-preset", "p4", "-cq", "20"], "GPU"),
        ("libx264", ["-preset", "veryfast", "-crf", "20"], "CPU"),
    ]
    for encoder, quality_args, device in encoders:
        if device == "CPU":
            q.put(("log", "No se pudo usar NVENC; convirtiendo con CPU para que la descarga siga funcionando"))
        for sync in (["-fps_mode", "cfr"], ["-vsync", "cfr"]):
            try:
                if os.path.exists(dst):
                    os.remove(dst)
            except OSError:
                pass
            cmd = [ff, "-y", "-i", src, "-map", "0:v:0", "-map", "0:a:0?",
                   "-c:v", encoder, *quality_args, "-profile:v", "high",
                   "-pix_fmt", "yuv420p", *sync, "-c:a", "copy",
                   "-map_metadata", "0", "-movflags", "+faststart", dst]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   creationflags=NO_WINDOW, timeout=1800)
            except Exception as e:
                err = str(e)
                continue
            err = (r.stderr or "")[-200:].strip()
            if r.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) <= 0:
                continue

            def safe_replace(src_path, dst_path):
                for _ in range(5):
                    try:
                        os.replace(src_path, dst_path)
                        return True
                    except PermissionError:
                        time.sleep(1)
                return False

            if safe_replace(dst, final):
                if os.path.abspath(final) != os.path.abspath(src):
                    try: os.remove(src)
                    except Exception: pass
                q.put(("log", f"Video convertido a H.264 8-bit (cuadros constantes, {device})"))
                q.put(("note", f"Video convertido a H.264 ({why}) para que DaVinci no lo marque offline."))
                return final
    try:
        if os.path.exists(dst): os.remove(dst)
    except Exception:
        pass
    q.put(("log", "No pude convertir el video a H.264 (se deja el original): " + err))
    q.put(("note", f"OJO: el video es {why} y no pude convertirlo; DaVinci puede marcarlo offline."))
    return src

def check_and_fix_video(ff, path, q):
    info = probe(ff, path)
    q.put(("log", "Análisis: " + stream_summary(ff, path)))
    low = info.lower()
    for line in low.splitlines():
        if "stream #" in line and "video:" in line:
            if re.search(r"\b(hevc|h\.?265)\b", line):
                q.put(("note", "Aviso: el video es HEVC/H.265 (no se modificó). El DaVinci gratuito puede no leerlo."))
            elif "yuv420p" not in line and "yuvj420p" not in line and "pix" not in line:
                if re.search(r"yuv4[24]\dp?\d*|10le|10be|gbr", line):
                    q.put(("note", "Aviso: el video no es 8-bit 4:2:0 (no se modificó). El DaVinci gratuito puede rechazarlo."))
            break
    q.put(("stage", 2, "Verificando audio"))
    path = ensure_mp4_aac(ff, path, q)
    q.put(("log", "Archivo final: " + stream_summary(ff, path)))
    report_audio(ff, path, q)
    return path

def stream_summary(ff, path):
    out = []
    for line in probe(ff, path).splitlines():
        t = line.strip()
        if t.startswith("Stream #") and ("Video:" in t or "Audio:" in t):
            t = re.sub(r"^Stream #\d+:\d+(\[0x[0-9a-fA-F]+\])?(\([^)]*\))?:\s*", "", t)
            out.append(t[:120])
    return " | ".join(out) or "sin información"

def to_pcm_mov(ff, src, q):
    info = probe(ff, src)
    if "Audio:" not in info:
        q.put(("log", "ATENCION: el archivo descargado NO trae pista de audio"))
        return src
    base = os.path.splitext(src)[0]
    dst = base + ".indiedl_tmp.mov"
    final = base + ".mov"
    cmd = [ff, "-y", "-i", src,
           "-map", "0:v:0?", "-c:v", "copy",
           "-map", "0:a:0", "-c:a", "pcm_s16le", "-ar", "48000",
           "-af", "aresample=async=1:first_pts=0"]
    if re.search(r"\b(hevc|h\.?265)\b", info.lower()):
        cmd += ["-tag:v", "hvc1"]
    cmd.append(dst)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=900)
    except Exception as e:
        q.put(("log", "No pude convertir el audio: " + str(e)))
        return src
    if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
        def safe_replace(src_path, dst_path):
            for _ in range(5):
                try:
                    os.replace(src_path, dst_path)
                    return True
                except PermissionError:
                    time.sleep(1)
            return False
        if safe_replace(dst, final):
            if os.path.abspath(final) != os.path.abspath(src):
                try: os.remove(src)
                except Exception: pass
            q.put(("log", "Video copiado sin cambios + audio PCM 48 kHz (.mov)"))
            return final
    try:
        if os.path.exists(dst):
            os.remove(dst)
    except Exception:
        pass
    q.put(("log", "No pude convertir el audio: " + (r.stderr or "")[-160:].strip()))
    return src

def gallery_dl_command():
    exe = shutil.which("gallery-dl")
    if exe:
        return [exe]
    return [sys.executable, "-m", "gallery_dl"]

def _profile_dirs(root):
    found = []
    try:
        for child in root.iterdir():
            if child.is_dir() and ((child / "cookies.sqlite").exists() or
                                   (child / "places.sqlite").exists()):
                found.append(child)
    except OSError:
        pass
    return found

def browser_profile_candidates():
    if os.name != "nt":
        return []
    roaming = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    candidates = []
    roots = [
        ("zen", roaming / "zen" / "Profiles"),
        ("zen", roaming / "Zen" / "Profiles"),
        ("zen", roaming / "zen-browser" / "Profiles"),
        ("zen", roaming / "Zen Browser" / "Profiles"),
        ("firefox", roaming / "Mozilla" / "Firefox" / "Profiles"),
    ]
    for browser, root in roots:
        for profile in _profile_dirs(root):
            db = profile / "cookies.sqlite"
            try:
                stamp = db.stat().st_mtime if db.exists() else 0
            except OSError:
                stamp = 0
            candidates.append({"browser": browser, "profile": str(profile), "stamp": stamp})
    chromium_roots = [
        ("chrome", local / "Google" / "Chrome" / "User Data"),
        ("edge", local / "Microsoft" / "Edge" / "User Data"),
        ("brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
    ]
    for browser, root in chromium_roots:
        for name in ("Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4"):
            profile = root / name
            if (profile / "Network" / "Cookies").exists() or (profile / "Cookies").exists():
                candidates.append({"browser": browser, "profile": str(profile), "stamp": 0})
    candidates.sort(key=lambda c: (c["browser"] in ("zen", "firefox"), c["stamp"]), reverse=True)
    return candidates

def find_zen_profile():
    return next((c["profile"] for c in browser_profile_candidates() if c["browser"] == "zen"), None)

def cookie_source(cfg):
    cfg = cfg or {}
    choice = str(cfg.get("cookies_browser", "auto") or "auto").strip().lower()
    if choice in ("auto", "zen", "firefox"):
        candidates = browser_profile_candidates()
        if choice == "zen":
            found = next((c for c in candidates if c["browser"] == "zen"), None)
            if not found:
                raise RuntimeError("No encontré un perfil de Zen Browser con cookies. Abrí Zen e iniciá sesión en Instagram.")
            return "firefox", found["profile"]
        if choice == "firefox":
            found = next((c for c in candidates if c["browser"] == "firefox"), None)
            if not found:
                raise RuntimeError("No encontré un perfil de Firefox con cookies. Abrí Firefox e iniciá sesión en Instagram.")
            return "firefox", found["profile"]
        found = next((c for c in candidates if c["browser"] == "zen"), None)
        if not found:
            found = next((c for c in candidates if c["browser"] == "firefox"), None)
        if found:
            return "firefox", found["profile"]
        for browser in ("chrome", "edge", "brave"):
            if any(c["browser"] == browser for c in candidates):
                log(f"Cookies: usando {browser} sin verificar sesión de Instagram. "
                    "Si falla, elegí Zen/Firefox en ⚙ SESIÓN IG.")
                return browser, None
        return None, None
    if choice in ("chrome", "edge", "brave", "chromium", "opera", "vivaldi"):
        return choice, None
    if choice.startswith("firefox:"):
        profile = choice.split(":", 1)[1].strip().strip('"')
        if profile and Path(profile).exists():
            return "firefox", profile
        raise RuntimeError("La ruta del perfil Firefox/Zen configurado ya no existe. Elegí Auto o seleccioná el navegador otra vez.")
    raise RuntimeError("Navegador de cookies no reconocido. Elegí Auto, Zen, Firefox, Chrome, Edge o Brave en ⚙ SESIÓN.")

def gallery_dl_args(cfg):
    args = gallery_dl_command()
    browser, profile = cookie_source(cfg)
    if browser:
        selector = f"{browser}:{profile}" if profile else browser
        args.extend(["--cookies-from-browser", selector])
        log(f"Cookies para gallery-dl: navegador={browser}, perfil={'detectado' if profile else 'predeterminado'}")
    else:
        log("Cookies del navegador no configuradas; gallery-dl intentará acceder sin sesión.")
    return args

def gallery_dl_extract(url, cfg, timeout=90):
    cmd = gallery_dl_args(cfg) + ["--dump-json", "--simulate", "--no-colors", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=NO_WINDOW)
    except FileNotFoundError as exc:
        raise RuntimeError("No está instalado gallery-dl. Ejecutá el instalador actualizado de IndieDL.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Instagram tardó demasiado en responder. Probá de nuevo o revisá la sesión del navegador.") from exc
    lines = (proc.stdout or "").splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict):
            direct = (data.get("_url") or data.get("url") or data.get("file_url")
                      or data.get("gdl_file_url"))
            if not direct:
                for key in ("metadata", "data", "file"):
                    nested = data.get(key)
                    if isinstance(nested, dict):
                        direct = (nested.get("_url") or nested.get("url") or nested.get("file_url")
                                  or nested.get("gdl_file_url"))
                        if direct:
                            data = {**data, **nested}
                            break
            if direct:
                data["_indiedl_url"] = direct
                entries.append(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    direct = item.get("_url") or item.get("url") or item.get("file_url")
                    if direct:
                        item["_indiedl_url"] = direct
                        entries.append(item)
    if not entries:
        detail = (proc.stderr or proc.stdout or "").strip()
        if proc.returncode:
            detail = detail[-1000:]
        if not detail:
            detail = "gallery-dl no devolvió elementos de imagen para este enlace."
        if any(word in detail.lower() for word in ("login", "cookie", "401", "403", "checkpoint", "challenge", "redirect to login")):
            detail += "\nInstagram rechazó la sesión usada. En IndieDL abrí ⚙ SESIÓN IG y elegí el navegador donde realmente está abierta tu cuenta. Si acabás de reinstalar Windows, iniciá sesión otra vez en ese navegador. Cerralo por completo y reintentá para liberar la base de cookies."
        if not detail.startswith("Instagram") and "instagram.com" in url.lower():
            detail += "\nSi el post es un video (no carrusel de fotos), usá el modo VIDEO."
        raise RuntimeError(detail[:1300])
    return entries

def gallery_dl_download(url, folder, cfg, q, cancel, image_indices=None):
    entries = gallery_dl_extract(url, cfg)
    total = len(entries)
    chosen = list(range(1, total + 1)) if not image_indices else [int(i) for i in image_indices]
    chosen = [i for i in chosen if 1 <= i <= total]
    if not chosen:
        raise RuntimeError("No hay imágenes seleccionadas para descargar.")
    os.makedirs(folder, exist_ok=True)
    title = str(entries[0].get("description") or entries[0].get("post_id") or "Instagram")
    q.put(("log", "Extractor: gallery-dl"))
    q.put(("log", f"Imágenes detectadas: {total} · seleccionadas: {len(chosen)}"))
    if cancel.is_set():
        raise RuntimeError("Cancelado")
    q.put(("stage", 1, f"Descargando imágenes ({len(chosen)} seleccionadas)"))
    q.put(("prog", 0.0, None, None, 0, 0, 0, len(chosen)))
    rango = ",".join(str(i) for i in chosen)
    args = gallery_dl_args(cfg) + [
        "--directory", folder,
        "--filename", "{post_id}_{num}.{extension}",
        "--range", rango,
        "--no-colors",
        url,
    ]
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=300, creationflags=NO_WINDOW)
    if cancel.is_set():
        raise RuntimeError("Cancelado")
    if proc.returncode:
        detail = (proc.stderr or proc.stdout or f"gallery-dl terminó con código {proc.returncode}").strip()
        if any(word in detail.lower() for word in ("login", "cookie", "401", "403", "checkpoint", "challenge", "redirect to login")):
            detail += "\nInstagram no aceptó las cookies usadas por IndieDL. Si usás Zen, cerralo por completo y reintentá."
        raise RuntimeError(detail[-1100:])
    q.put(("log", f"Imágenes descargadas: {len(chosen)}"))
    q.put(("prog", 1.0, None, 0, 0, 0, len(chosen), len(chosen)))
    q.put(("done", folder, title))

def ensure_temp_dir():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = str(TEMP_DIR.resolve())
    os.environ["TEMP"] = temp_path
    os.environ["TMP"] = temp_path
    os.environ["TMPDIR"] = temp_path
    tempfile.tempdir = temp_path
    try: os.chdir(str(APP_DIR))
    except OSError: pass
    return temp_path

def ytdlp_exe():
    cands = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        cands.append(os.path.join(local, "Microsoft", "WinGet", "Links", "yt-dlp.exe"))
    w = shutil.which("yt-dlp")
    if w:
        cands.append(w)
    venv = str(APP_DIR / "venv").lower()
    for c in cands:
        if c and os.path.isfile(c) and not os.path.abspath(c).lower().startswith(venv):
            return c
    return None

def _num(s):
    try:
        v = float(s)
        return v if v == v else None
    except (TypeError, ValueError):
        return None

PROG_RE = re.compile(r"^IDLP\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)")

def parse_progress(line):
    m = PROG_RE.match(line.strip())
    if not m:
        return None
    dl, tot, est, sp, eta = (_num(x) for x in m.groups())
    return (dl or 0, tot or est or 0, sp, eta)

def exe_download(exe, url, mode, folder, cfg, q, quality, cancel, section=None):
    ff = ffmpeg_path()
    t0 = time.time()
    done_file = TEMP_DIR / f"final_{int(t0)}.txt"
    cmd = [exe, "--newline", "--no-colors", "--no-playlist", "--windows-filenames",
           "--no-mtime",
           "--retries", "10", "--fragment-retries", "10", "--socket-timeout", "30",
           "--concurrent-fragments", "4",
           "-P", f"home:{folder}", "-P", f"temp:{TEMP_DIR}",
           "-o", "%(title).80s [%(id)s].%(ext)s",
           "--progress-template", "download:IDLP|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
                                  "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
           "--print-to-file", "after_move:%(title)s|||%(filepath)s", str(done_file)]
    if ff:
        cmd += ["--ffmpeg-location", ff]
    if mode == "audio":
        cmd += ["-f", "bestaudio/best", "-x", "--audio-format", quality or AUDIO_CODEC]
        if (quality or AUDIO_CODEC) != "wav":
            cmd += ["--audio-quality", AUDIO_QUALITY + "K"]
    else:
        cmd += ["-f", vfmt(quality), "--merge-output-format", "mp4"]
        if section:
            cmd += ["--download-sections", f"*{section[0]}-{section[1]}", "--force-keyframes-at-cuts",
                    "--postprocessor-args", "ffmpeg:-c:v h264_nvenc -preset p4 -cq 20 -pix_fmt yuv420p -profile:v high -fps_mode cfr"]
    if "instagram.com" in url.lower():
        try:
            browser, profile = cookie_source(cfg)
            if browser:
                cmd += ["--cookies-from-browser", f"{browser}:{profile}" if profile else browser]
                q.put(("log", "Sesión de Instagram: cookies de " + ("Zen/Firefox" if profile else browser)))
        except Exception as exc:
            q.put(("log", f"Sin cookies de Instagram: {exc}"))
    cmd.append(url)
    log("exe: " + " ".join(cmd))
    q.put(("stage", 0, "Conectando…"))
    q.put(("log", "Motor: yt-dlp.exe (Aceleración GPU activa)"))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=NO_WINDOW, cwd=str(APP_DIR))
    n_files, started, errors, tail = 0, False, [], []
    try:
        for raw in proc.stdout:
            if cancel.is_set():
                proc.kill()
                raise Exception("Cancelado")
            line = raw.strip()
            if not line:
                continue
            pr = parse_progress(line)
            if pr:
                dl, tot, sp, eta = pr
                if not started:
                    started = True
                    q.put(("stage", 1, "Descargando"))
                q.put(("prog", (dl / tot) if tot else 0, sp, eta, dl, tot, max(n_files, 1), max(n_files, 1)))
                continue
            tail.append(line)
            tail = tail[-12:]
            if line.startswith("ERROR"):
                errors.append(line.replace("ERROR: ", "", 1))
            elif line.startswith("[download] Destination:"):
                n_files += 1
                q.put(("log", "Archivo " + str(n_files) + ": " + os.path.basename(line.split(":", 1)[1].strip())))
            elif line.startswith("[Merger]"):
                q.put(("stage", 2, "Uniendo audio y video")); q.put(("log", "Uniendo audio y video"))
            elif line.startswith("[ExtractAudio]"):
                q.put(("stage", 2, "Convirtiendo a " + (quality or AUDIO_CODEC))); q.put(("log", "Convirtiendo audio"))
            elif line.startswith("[MoveFiles]"):
                q.put(("stage", 3, "Guardando archivo"))
            elif line.startswith("[") and not line.startswith("[download]"):
                q.put(("log", line[:90]))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    title, final = "", None
    try:
        for ln in done_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "|||" in ln:
                title, final = ln.split("|||", 1)
                final = final.strip()
    except OSError:
        pass
    finally:
        try: done_file.unlink()
        except OSError: pass
    if not final or not os.path.isfile(final):
        fresh = [p for p in Path(folder).glob("*") if p.is_file()
                 and t0 - 2 <= p.stat().st_mtime <= t0 + 600
                 and not p.name.endswith((".part", ".ytdl", ".temp"))]
        final = str(max(fresh, key=lambda p: p.stat().st_mtime)) if fresh else None
    if proc.returncode != 0 and not final:
        raise RuntimeError((errors[-1] if errors else "; ".join(tail[-3:]) or "yt-dlp.exe falló")[:400])
    if not final:
        raise RuntimeError("yt-dlp.exe terminó pero no encontré el archivo descargado.")
    return final, title

def run_download(url, mode, folder, cfg, q, quality, cancel, section=None, image_indices=None, cached_info=None):
    try:
        # Evitar que una URL de inicio de TikTok/Instagram llegue a yt-dlp como si fuera un vídeo.
        from urllib.parse import urlparse
        parsed_url = urlparse(str(url or "").strip())
        host = (parsed_url.hostname or "").lower()
        path = (parsed_url.path or "").strip("/")
        if host.endswith("tiktok.com") and (not path or path in {"foryou", "following", "explore"}):
            raise RuntimeError(
                "Se recibió la página principal de TikTok, no un vídeo. "
                "Volvé a TikTok, esperá a que el vídeo esté visible y usá el botón de IndieDL otra vez."
            )
        if host.endswith("instagram.com") and (not path or path in {"reels", "explore"}):
            raise RuntimeError(
                "Se recibió una página general de Instagram, no un Reel/publicación. "
                "Abrí el Reel o publicación concreta y volvé a intentarlo."
            )

        temp_path = ensure_temp_dir()
        q.put(("stage", 0, "Descargando"))
        q.put(("log", "Iniciando descarga de " + site_name(url).title()))
        q.put(("log", "Directorio temporal activo: " + temp_path))
        if mode == "image":
            gallery_dl_download(url, folder, cfg, q, cancel, image_indices)
            return

        ff = ffmpeg_path()
        if mode in ("video", "audio") and not ff:
            raise RuntimeError(
                "Falta ffmpeg. Instalá ffmpeg (winget install Gyan.FFmpeg) "
                "o reinstalá IndieDL. Sin ffmpeg no se puede unir audio y video."
            )

        exe = ytdlp_exe() if mode in ("video", "audio") else None
        if exe:
            final, _title = exe_download(exe, url, mode, folder, cfg, q, quality, cancel, section)
            st = {"files": [], "meta": True, "title": _title}
            res = {"title": _title}
        else:
            q.put(("log", "yt-dlp.exe no encontrado; usando el motor interno"))
            import yt_dlp
            st = {"files": [], "meta": False, "title": ""}

            def hook(d):
                if cancel.is_set():
                    raise Exception("Cancelado")
                info = d.get("info_dict") or {}
                fn = d.get("filename") or d.get("tmpfilename") or ""
                total = len(info.get("requested_formats") or [1])
                if d["status"] == "downloading":
                    if fn not in st["files"]:
                        st["files"].append(fn)
                        if not st["meta"]:
                            st["meta"] = True
                            st["title"] = info.get("title", "") or ""
                            q.put(("log", "Titulo: " + (st["title"] or "-")))
                            who = info.get("channel") or info.get("uploader")
                            if who:
                                q.put(("log", "Autor: " + str(who)))
                            if info.get("duration"):
                                q.put(("log", "Duracion: " + ft(info["duration"])))
                        n = len(st["files"])
                        q.put(("log", f"Archivo {n} de {total}: " + str(info.get("format") or info.get("ext") or "")))
                        q.put(("stage", 1, f"Descargando ({n} de {total})" if total > 1 else "Descargando"))
                    n = max(len(st["files"]), 1)
                    tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    dl = d.get("downloaded_bytes", 0)
                    p = dl / tot if tot else 0
                    q.put(("prog", ((n - 1) + p) / total, d.get("speed"), d.get("eta"), dl, tot, n, total))
                elif d["status"] == "finished":
                    st["title"] = st["title"] or info.get("title", "") or ""
                    q.put(("log", "Descargado: " + fb(d.get("total_bytes") or d.get("downloaded_bytes"))))

            def phook(d):
                name = d.get("postprocessor", "")
                if d.get("status") != "started":
                    return
                if name == "MoveFiles":
                    q.put(("stage", 3, "Guardando archivo"))
                    q.put(("log", "Moviendo a la carpeta final"))
                else:
                    txt = {"Merger": "Uniendo audio y video",
                           "ExtractAudio": "Convirtiendo a " + (quality or AUDIO_CODEC),
                           "VideoRemuxer": "Reempaquetando video"}.get(name, "Procesando")
                    q.put(("stage", 2, txt))
                    q.put(("log", txt))

            image_prefix = "%(playlist_index)02d - " if mode == "image" else ""
            opts = {
                "outtmpl": os.path.join(folder, image_prefix + "%(title).80s [%(id)s].%(ext)s"),
                "noplaylist": mode != "image", "quiet": True, "no_warnings": True, "noprogress": True,
                "windowsfilenames": True, "progress_hooks": [hook], "postprocessor_hooks": [phook],
                "concurrent_fragment_downloads": 4,
                "paths": {"home": folder, "temp": str(TEMP_DIR)},
            }
            if ff:
                opts["ffmpeg_location"] = ff
            if mode == "video":
                opts.update(format=vfmt(quality), merge_output_format="mp4")
                if section:
                    opts["download_sections"] = [f"*{section[0]}-{section[1]}"]
                    opts["force_keyframes_at_cuts"] = True
                    opts["postprocessor_args"] = {
                        "ffmpeg": ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20", "-pix_fmt", "yuv420p", "-profile:v", "high", "-fps_mode", "cfr"]
                    }
            elif mode == "audio":
                opts.update(format="bestaudio/best", postprocessors=[{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": quality or AUDIO_CODEC, "preferredquality": AUDIO_QUALITY}])
            else:
                raise RuntimeError("Modo imagen debe ir por gallery-dl.")

            res = None
            if cached_info and mode in ("video", "audio"):
                try:
                    with yt_dlp.YoutubeDL(opts) as y:
                        res = y.process_ie_result(cached_info, download=True)
                except Exception as exc:
                    q.put(("log", f"Cached info falló; reextrayendo: {type(exc).__name__}: {exc}"))
                    res = None
            if res is None:
                with yt_dlp.YoutubeDL(opts) as y:
                    res = y.extract_info(url, download=True)

            candidates = []
            if isinstance(res, dict):
                for key in ("filepath", "_filename"):
                    value = res.get(key)
                    if value:
                        candidates.append(value)
                for item in (res.get("requested_downloads") or []):
                    if isinstance(item, dict):
                        for key in ("filepath", "_filename"):
                            value = item.get(key)
                            if value:
                                candidates.append(value)
            final = next(
                (os.path.abspath(path) for path in candidates
                 if isinstance(path, str) and os.path.isfile(path) and os.path.getsize(path) > 0),
                None
            )

        if final and os.path.isfile(final):
            final = safe_media_name(final, q)
        if mode == "video" and final and ff:
            final = ensure_h264(ff, final, q)
            if cfg.get("pcm_resolve", False):
                q.put(("log", "Origen descargado: " + stream_summary(ff, final)))
                q.put(("stage", 2, "Audio a PCM (.mov)"))
                converted = to_pcm_mov(ff, final, q)
                final = ensure_mp4_aac(ff, final, q) if converted == final else converted
                q.put(("log", "Archivo final: " + stream_summary(ff, final)))
                report_audio(ff, final, q)
            else:
                final = check_and_fix_video(ff, final, q)

        if not final or not os.path.isfile(final) or os.path.getsize(final) <= 0:
            raise RuntimeError(
                "yt-dlp terminó, pero IndieDL no encontró un archivo final válido "
                "en la carpeta de destino. Revisá el registro."
            )

        if mode == "video" and ff and "Audio:" not in probe(ff, final):
            q.put(("log", "ATENCION: el archivo final NO trae pista de audio"))
        q.put(("stage", 3, "Finalizando"))
        q.put(("log", "Archivo final verificado: " + os.path.basename(final)))
        q.put(("done", os.path.dirname(final), st["title"] or (res or {}).get("title") or url))
    except Exception as e:
        err_text = str(e).replace("ERROR: ", "").strip()
        log(f"download {url}: {e!r}\n{traceback.format_exc()}")
        if not err_text:
            err_text = (f"Error interno de yt-dlp: {type(e).__name__}. "
                        r"Se guardó el detalle en %LOCALAPPDATA%\IndieDL\indiedl.log.")
        if "tiktok.com" in url.lower() and any(term in err_text.lower() for term in (
                "unexpected response from webpage request", "solve_challenge", "challenge", "http error 403")):
            err_text = ("TikTok rechazó la conexión o no completó el desafío con Firefox. Puede deberse a la IP/red "
                        "(VPN, proxy, datos móviles compartidos), a un bloqueo temporal o a cambios de TikTok. "
                        "Probá otra red y reintentá. "
                        r"Revisá el registro en %LOCALAPPDATA%\IndieDL\indiedl.log.")
        q.put(("err", err_text[:420]))

def site_name(u):
    u = u.lower()
    for k, n in (("youtu", "YOUTUBE"), ("instagram", "INSTAGRAM"), ("tiktok", "TIKTOK"),
                 ("x.com", "X"), ("twitter", "X"), ("t.co/", "X"), ("pinterest", "PINTEREST"),
                 ("pin.it", "PINTEREST")):
        if k in u:
            return n
    return "LINK"

def spaced(s):
    return "   ".join(" ".join(w) for w in s.split())

def halftone_header(w, h):
    import math
    from PIL import Image, ImageDraw, ImageFont
    S = 2
    W, H = w * S, h * S
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    step = 13
    for row, y in enumerate(range(0, H, step)):
        for x in range(0, W, step):
            xx = x + (step // 2 if row % 2 else 0)
            il = max(0.0, 1 - math.hypot(xx, y) / (0.42 * W))
            ir = max(0.0, 1 - math.hypot(W - xx, y) / (0.30 * W))
            i = max(il, ir) ** 1.1
            r = i * step * 0.62
            if r > 0.8:
                d.ellipse([xx - r, y - r, xx + r, y + r], fill="black")
    d.polygon([(int(W * .27), 0), (int(W * .32), 0), (int(W * .23), int(H * .55)), (int(W * .19), int(H * .55))],
              fill="black")
    font = None
    for p in ("C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/arialbd.ttf",
              "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(p, 118)
            break
        except Exception:
            pass
    font = font or ImageFont.load_default()
    text = "INDIE NOW"
    bx = d.textbbox((0, 0), text, font=font)
    tw, th = bx[2] - bx[0], bx[3] - bx[1]
    tx, ty = (W - tw) // 2 - bx[0], (H - th) // 2 - bx[1] - 6
    d.rectangle([tx + bx[0] - 14, ty + bx[1] + int(th * .55), tx + bx[2] + 14, ty + bx[3] + 6], fill="#FFF933")
    d.text((tx, ty), text, font=font, fill="black")
    return img

def build_app():
    import customtkinter as ctk
    from tkinter import filedialog, messagebox
    ctk.set_appearance_mode("dark")
    BLACK, WHITE, YEL, YEL_H = "#0A0D10", "#F4F6F8", "#FFF333", "#FFE600"
    GRAY, RED, GREEN = "#AAB4BE", "#FF5B65", "#4ADE80"
    HEAVY = "Segoe UI Black"
    VIDEO_Q = ["Mejor", "1080p", "720p"]
    AUDIO_F = ["wav", "mp3", "m4a"]
    IMAGE_F = ["Original"]
    QFONT = "Segoe UI"
    SPIN = "|/-\\"

    class App(ctk.CTk):
        def __init__(self, mode, url, batch=None, clip=None):
            super().__init__()
            self.cfg = load_cfg()
            self.batch = []
            self.batch_mode = False
            self.batch_ctx = None
            self._prefix = ""
            self.q = queue.Queue()
            self.busy = False
            self.cancel = threading.Event()
            self.cur_mode = mode if mode in ("video", "audio", "image") else "video"
            self._image_dialog = None
            self._image_selection_ready = False
            self._image_indices = None
            self._skip_folder_once = False
            self._folder_explicit = False
            self._carousel_thumb_refs = []
            self._metadata_cache = {}
            self._metadata_loading = set()
            self._last_clip_url = None
            self._gallery_dl_ok = self._check_gallery_dl()
            self.stage = -1
            self.spin_i = 0
            self.t0 = time.time()
            self.title("Indie Now DL")
            # Abrir ocupando el escritorio para que las opciones queden a la
            # vista en dos columnas y no sea necesario desplazarse.
            self.geometry("1520x920")
            self.minsize(1180, 680)
            self.resizable(True, True)
            try:
                self.state("zoomed")
            except Exception:
                pass
            self.configure(fg_color="#0D1116")
            self.attributes("-topmost", True)
            self.after(800, lambda: self.attributes("-topmost", False))
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=0)
            self.grid_rowconfigure(0, weight=1)

            left = ctk.CTkFrame(self, fg_color="#0D1116", corner_radius=0)
            left.grid(row=0, column=0, sticky="nsew")
            right = ctk.CTkFrame(self, fg_color=BLACK, corner_radius=0, width=340)
            right.grid(row=0, column=1, sticky="nsew")
            right.grid_propagate(False)

            self.hdr = ctk.CTkImage(halftone_header(1040, 120), size=(1040, 120))
            hf = ctk.CTkFrame(left, fg_color="#0D1116", corner_radius=0, height=120)
            hf.pack(fill="x")
            hf.pack_propagate(False)
            ctk.CTkLabel(hf, text="", image=self.hdr).place(relx=0.5, rely=0.5, anchor="center")
            band = ctk.CTkFrame(left, fg_color=BLACK, corner_radius=0, height=42)
            band.pack(fill="x")
            band.pack_propagate(False)
            ctk.CTkLabel(band, text=spaced("DESCARGA VIDEOS, AUDIOS E IMÁGENES"), text_color=YEL,
                         font=(HEAVY, 15)).pack(expand=True)
            ctk.CTkFrame(left, fg_color=YEL, corner_radius=0, height=5).pack(fill="x")

            body = ctk.CTkFrame(left, fg_color="#0D1116", corner_radius=0)
            body.pack(fill="both", expand=True, padx=22, pady=(16, 14))
            self.form = ctk.CTkFrame(body, fg_color="#0D1116", corner_radius=0)
            self.form.pack(fill="both", expand=True)
            self.form.grid_columnconfigure((0, 1), weight=1, uniform="form")
            self.form.grid_rowconfigure(0, weight=1)
            self.pv = ctk.CTkFrame(body, fg_color="#0D1116", corner_radius=0)
            self.build_form(url)
            self.build_progress()

            hd = ctk.CTkFrame(right, fg_color="transparent")
            hd.pack(fill="x", padx=16, pady=(18, 8))
            self.r_title = ctk.CTkLabel(hd, text="▤  Historial", font=(HEAVY, 17), text_color=YEL)
            self.r_title.pack(side="left")
            self.b_hist = ctk.CTkButton(hd, text="▤ HIST.", width=68, height=26, corner_radius=3,
                                        font=(HEAVY, 10), command=lambda: self.show_panel("hist"))
            self.b_live = ctk.CTkButton(hd, text="● EN VIVO", width=84, height=26, corner_radius=3,
                                        font=(HEAVY, 10), command=lambda: self.show_panel("live"))
            self.b_live.pack(side="right")
            self.b_hist.pack(side="right", padx=(0, 6))
            self.rbar = ctk.CTkProgressBar(right, height=4, corner_radius=0, fg_color="#222", progress_color=YEL)
            self.rbar.set(0)
            self.rbar.pack(fill="x", padx=16)
            self.hist = ctk.CTkScrollableFrame(right, fg_color=BLACK, corner_radius=0, scrollbar_button_color="#333")
            self.live = ctk.CTkScrollableFrame(right, fg_color=BLACK, corner_radius=0, scrollbar_button_color="#333")
            self.panel = None
            self.render_hist()
            self.show_panel("hist")

            self.set_mode(self.cur_mode)
            if not self._gallery_dl_ok:
                try:
                    self.b_image.configure(state="disabled")
                    self.b_image.configure(text="▧  IMAGEN (sin gallery-dl)")
                except Exception:
                    pass
            if batch:
                self.enter_batch(batch)
            if clip:
                self.after(500, lambda c=clip: self.apply_clip(c))
            self.bind("<Return>", lambda e: self.start() if self.form.winfo_ismapped() else None)
            self.after(100, self.poll)
            self.after(120, self.tick)

        def _check_gallery_dl(self):
            try:
                proc = subprocess.run(
                    gallery_dl_command() + ["--version"],
                    capture_output=True, timeout=10,
                    creationflags=NO_WINDOW, check=False,
                )
                ok = proc.returncode == 0
                if not ok:
                    log(f"gallery-dl no disponible (rc={proc.returncode}): {proc.stderr[:200]!r}")
                return ok
            except Exception as exc:
                log(f"gallery-dl no disponible: {exc!r}")
                return False

        def build_form(self, url):
            # La columna izquierda agrupa enlace y vista previa. La derecha
            # contiene las opciones y el botón principal.
            left_stack = ctk.CTkFrame(self.form, fg_color="transparent")
            left_stack.grid(row=0, column=0, sticky="new", padx=(0, 8))
            right_stack = ctk.CTkFrame(self.form, fg_color="transparent")
            right_stack.grid(row=0, column=1, sticky="new", padx=(8, 0))

            c1 = self.card(left_stack)
            self.c1 = c1
            c1.pack(fill="x")
            top = ctk.CTkFrame(c1, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(12, 6))
            self.badge(top, "1").pack(side="left")
            ctk.CTkLabel(top, text="↗  Link del contenido", font=(HEAVY, 16), text_color=WHITE).pack(side="left", padx=10)
            self.chip = ctk.CTkLabel(top, text="🔗  LINK", fg_color="#252C33", text_color=YEL, corner_radius=8,
                                     font=(HEAVY, 11), width=112, height=28)
            self.chip.pack(side="right")
            self.cookies_btn = ctk.CTkButton(top, text="⚙ SESIÓN IG", width=104, height=28, corner_radius=8,
                                             fg_color="#252C33", hover_color="#343D46", text_color=WHITE,
                                             font=(HEAVY, 10), command=self.configure_cookies)
            self.cookies_btn.pack(side="right", padx=(0, 8))
            self.last_btn = ctk.CTkButton(top, text="", width=140, height=28, corner_radius=8,
                                          fg_color="#252C33", hover_color="#343D46", text_color=YEL,
                                          font=(QFONT, 10, 'bold'), command=self.load_last_batch)
            self.refresh_last_btn()
            self.url = ctk.CTkEntry(c1, height=42, corner_radius=4, fg_color="#20272E", border_color="#39434D",
                                    border_width=2, text_color=WHITE, placeholder_text_color="#8D99A5",
                                    font=("Segoe UI", 13),
                                    placeholder_text="Pega un enlace de YouTube, Instagram, TikTok, X o Pinterest")
            self.url.pack(fill="x", padx=14, pady=(0, 14))
            if url:
                self.url.insert(0, url)
            self.url.bind("<KeyRelease>", lambda e: self.on_url())

            self.preview = self.card(left_stack)
            self.preview.pack(fill="x", pady=(10, 0))
            self.preview.grid_columnconfigure(1, weight=1)
            self.platform_icon = ctk.CTkLabel(self.preview, text="", image=self.make_platform_logo("LINK"),
                width=56, height=56, fg_color="transparent", corner_radius=12)
            self.platform_icon.grid(row=0, column=0, rowspan=2, padx=12, pady=12)
            self.thumbnail_label = ctk.CTkLabel(self.preview, text="", width=160, height=90,
                fg_color="#20272E", corner_radius=8)
            self.thumbnail_label.grid(row=0, column=2, rowspan=2, padx=(0, 12), pady=10)
            self.thumbnail_image = None
            self.preview_title = ctk.CTkLabel(self.preview, text="Vista previa del contenido",
                text_color=WHITE, font=("Segoe UI Semibold", 14), anchor="w", justify="left", wraplength=380)
            self.preview_title.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(13, 2))
            self.preview_meta = ctk.CTkLabel(self.preview, text="Pegá un enlace para detectar plataforma y detalles",
                text_color=GRAY, font=("Segoe UI", 11), anchor="w", justify="left", wraplength=400)
            self.preview_meta.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 13))
            self._meta_job = None

            blk = self.card(right_stack)
            self.blk = blk
            blk.pack(fill="x", pady=14)
            blk.grid_columnconfigure(2, weight=1)

            def rowtitle(r, n, text):
                self.badge(blk, n).grid(row=r, column=0, padx=(14, 8), pady=11)
                lbl = ctk.CTkLabel(blk, text=text, font=(HEAVY, 14), text_color=WHITE, width=100, anchor="w")
                lbl.grid(row=r, column=1, sticky="w")
                return lbl

            def sep(r):
                ctk.CTkFrame(blk, fg_color="#303942", height=1, corner_radius=0).grid(
                    row=r, column=0, columnspan=3, sticky="ew")

            rowtitle(0, "2", "Tipo")
            seg = ctk.CTkFrame(blk, fg_color="transparent")
            seg.grid(row=0, column=2, sticky="ew", padx=(0, 14))
            seg.grid_columnconfigure((0, 1, 2), weight=1, uniform="s")
            self.b_video = ctk.CTkButton(seg, text="▶  VIDEO", height=44, corner_radius=9, border_width=1,
                                         border_color="#39434D", font=(HEAVY, 12), command=lambda: self.set_mode("video"))
            self.b_audio = ctk.CTkButton(seg, text="♫  AUDIO", height=44, corner_radius=9, border_width=1,
                                         border_color="#39434D", font=(HEAVY, 12), command=lambda: self.set_mode("audio"))
            self.b_image = ctk.CTkButton(seg, text="▧  IMAGEN", height=44, corner_radius=9, border_width=1,
                                         border_color="#39434D", font=(HEAVY, 12), command=lambda: self.set_mode("image"))
            self.b_video.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            self.b_audio.grid(row=0, column=1, sticky="ew", padx=2)
            self.b_image.grid(row=0, column=2, sticky="ew", padx=(4, 0))
            sep(1)

            rowtitle(2, "3", "📁 Carpeta")
            fr = ctk.CTkFrame(blk, fg_color="transparent")
            fr.grid(row=2, column=2, sticky="ew", padx=(0, 14))
            fr.grid_columnconfigure(0, weight=1)
            self.folder = ctk.CTkEntry(fr, height=40, corner_radius=9, fg_color="#20272E", border_color="#39434D",
                                       border_width=2, text_color=WHITE, font=("Segoe UI", 12))
            self.folder.insert(0, self.cfg["last_dir"])
            self.folder.grid(row=0, column=0, sticky="ew")
            ctk.CTkButton(fr, text="📁  ELEGIR", width=104, height=38, corner_radius=8, fg_color="#252C33",
                          hover_color="#343D46", text_color=WHITE, font=(HEAVY, 12),
                          command=self.pick).grid(row=0, column=1, padx=(8, 0))
            sep(3)

            self.l_q = rowtitle(4, "4", "✦ Calidad")
            self.menu = ctk.CTkOptionMenu(blk, values=VIDEO_Q, height=40, corner_radius=9, fg_color=BLACK,
                                          button_color=BLACK, button_hover_color="#333", text_color=WHITE,
                                          dropdown_fg_color="#20272E", dropdown_text_color=WHITE,
                                          dropdown_hover_color=YEL, font=(HEAVY, 13), dropdown_font=("Segoe UI", 13))
            self.menu.grid(row=4, column=2, sticky="ew", padx=(0, 14))
            sep(5)

            rowtitle(6, "5", "⚙ Opciones")
            op = ctk.CTkFrame(blk, fg_color="transparent")
            op.grid(row=6, column=2, sticky="w")
            self.v_ask = ctk.BooleanVar(value=self.cfg["ask_folder"])
            self.v_close = ctk.BooleanVar(value=self.cfg["close_when_done"])
            self.v_pcm = ctk.BooleanVar(value=self.cfg.get("pcm_resolve", False))
            for text, var in (("▣  Preguntar carpeta", self.v_ask), ("✓  Cerrar al terminar", self.v_close),
                              ("♫  Audio PCM (.mov)", self.v_pcm)):
                ctk.CTkCheckBox(op, text=text, variable=var, text_color=WHITE, font=("Segoe UI Semibold", 12),
                                fg_color=YEL, hover_color=YEL_H, border_color=BLACK, checkmark_color=BLACK,
                                border_width=2, corner_radius=3, checkbox_width=20,
                                checkbox_height=20).pack(side="left", padx=(0, 12))

            sep(7)
            self.v_clip = ctk.BooleanVar(value=False)
            self.clip_toggle = ctk.CTkCheckBox(blk, text="✂  Recortar fragmento", variable=self.v_clip,
                            text_color=WHITE, font=("Segoe UI Semibold", 12), fg_color=YEL,
                            hover_color=YEL_H, border_color=BLACK, checkmark_color=BLACK,
                            border_width=2, corner_radius=3, checkbox_width=20, checkbox_height=20)
            self.clip_toggle.grid(row=8, column=0, columnspan=2, sticky="w", padx=14, pady=8)
            clip = ctk.CTkFrame(blk, fg_color="transparent")
            self.clip_frame = clip
            clip.grid(row=8, column=2, sticky="ew", padx=(0, 14), pady=8)
            clip.grid_columnconfigure((0, 1), weight=1)
            self.clip_start = ctk.CTkEntry(clip, height=32, placeholder_text="Desde 00:02:30")
            self.clip_end = ctk.CTkEntry(clip, height=32, placeholder_text="Hasta 00:03:45")
            self.clip_start.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            self.clip_end.grid(row=0, column=1, sticky="ew", padx=(4, 0))

            self.msg = ctk.CTkLabel(self.form, text="", text_color=RED, font=("Segoe UI Semibold", 12), anchor="w")
            self.msg.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            self.btn = ctk.CTkButton(self.form, text="⬇  DESCARGAR", height=56, corner_radius=12, fg_color=YEL,
                                     hover_color=YEL_H, text_color=BLACK, border_width=0, border_color=YEL,
                                     font=(HEAVY, 19), command=self.start)
            self.btn.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            self.on_url()

        def build_progress(self):
            self.p_top = ctk.CTkLabel(self.pv, text="", text_color=GRAY, font=("Segoe UI Semibold", 12), anchor="w")
            self.p_top.pack(fill="x")
            self.p_title = ctk.CTkLabel(self.pv, text="", text_color=WHITE, font=(HEAVY, 24), anchor="w")
            self.p_title.pack(fill="x", pady=(0, 6))
            self.p_sub = ctk.CTkLabel(self.pv, text="", text_color=GRAY, font=("Segoe UI", 12), anchor="w")
            self.p_sub.pack(fill="x", pady=(0, 10))

            card = self.card(self.pv)
            card.pack(fill="x")
            self.rows = []
            for i, name in enumerate(STAGES):
                r = ctk.CTkFrame(card, fg_color="transparent")
                r.pack(fill="x", padx=16, pady=(12 if i == 0 else 0, 12 if i == len(STAGES) - 1 else 0))
                r.grid_columnconfigure(1, weight=1)
                ic = ctk.CTkFrame(r, width=30, height=30, corner_radius=15, fg_color="#DDD")
                ic.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 12))
                ic.pack_propagate(False)
                il = ctk.CTkLabel(ic, text="", font=(HEAVY, 13), text_color=WHITE, fg_color="transparent")
                il.pack(expand=True)
                tx = ctk.CTkLabel(r, text=name, font=("Segoe UI Semibold", 15), text_color="#999", anchor="w")
                tx.grid(row=0, column=1, sticky="w", pady=(4, 0))
                pc = ctk.CTkLabel(r, text="", font=(HEAVY, 13), text_color=WHITE)
                pc.grid(row=0, column=2, sticky="e")
                bar = ctk.CTkProgressBar(r, height=10, corner_radius=0, fg_color="#E2E2E2", progress_color=BLACK,
                                         border_width=2, border_color=BLACK, mode="determinate")
                bar.set(0)
                ln = ctk.CTkFrame(r, width=2, height=18, fg_color="#CCC", corner_radius=0)
                if i < len(STAGES) - 1:
                    ln.grid(row=2, column=0, pady=(2, 0))
                self.rows.append(dict(ic=ic, il=il, tx=tx, pc=pc, bar=bar, name=name))

            st = ctk.CTkFrame(self.pv, fg_color="transparent")
            st.pack(fill="x", pady=14)
            st.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="c")
            self.stat = {}
            for c, (key, title) in enumerate((("sp", "VELOCIDAD"), ("eta", "RESTANTE"),
                                              ("sz", "TAMANO"), ("fi", "ARCHIVO"))):
                f = self.card(st)
                f.grid(row=0, column=c, sticky="ew", padx=(0 if c == 0 else 6, 0 if c == 3 else 6))
                ctk.CTkLabel(f, text=title, font=(HEAVY, 10), text_color=GRAY).pack(pady=(8, 0))
                v = ctk.CTkLabel(f, text="-", font=(HEAVY, 16), text_color=WHITE)
                v.pack(pady=(0, 8))
                self.stat[key] = v

            self.p_msg = ctk.CTkLabel(self.pv, text="", font=("Segoe UI Semibold", 12), anchor="w",
                                      wraplength=640, justify="left")
            self.p_msg.pack(fill="x")
            bt = ctk.CTkFrame(self.pv, fg_color="transparent")
            bt.pack(fill="x", side="bottom", pady=(0, 6))
            bt.grid_columnconfigure((0, 1), weight=1, uniform="b")
            self.b_cancel = ctk.CTkButton(bt, text="CANCELAR", height=48, corner_radius=4, fg_color="#20272E",
                                          hover_color="#303942", text_color=WHITE, border_width=3, border_color=BLACK,
                                          font=(HEAVY, 15), command=lambda: self.cancel.set())
            self.b_open = ctk.CTkButton(bt, text="ABRIR CARPETA", height=48, corner_radius=4, fg_color="#20272E",
                                        hover_color="#303942", text_color=WHITE, border_width=3, border_color=BLACK,
                                        font=(HEAVY, 15), command=lambda: self.open_dir(self.cfg["last_dir"]))
            self.b_back = ctk.CTkButton(bt, text="DESCARGAR OTRO", height=48, corner_radius=4, fg_color=YEL,
                                        hover_color=YEL_H, text_color=BLACK, border_width=3, border_color=BLACK,
                                        font=(HEAVY, 15), command=self.back)

        def show_buttons(self, mode):
            """Coloca los botones inferiores lado a lado, con el mismo ancho."""
            for b in (self.b_cancel, self.b_open, self.b_back):
                b.grid_remove()
            order = (self.b_cancel, self.b_open) if mode == "run" else (self.b_open, self.b_back)
            for i, b in enumerate(order):
                b.grid(row=0, column=i, sticky="ew", padx=(0, 6) if i == 0 else (6, 0))

        def set_stage(self, idx, text=None):
            self.stage = idx
            for i, r in enumerate(self.rows):
                if i < idx:
                    r["bar"].stop()
                    r["bar"].grid_forget()
                    r["ic"].configure(fg_color=YEL)
                    r["il"].configure(text="✓", text_color=BLACK)
                    r["tx"].configure(text=r["name"], text_color=WHITE, font=("Segoe UI Semibold", 15))
                    r["pc"].configure(text="")
                elif i == idx:
                    r["ic"].configure(fg_color=BLACK)
                    r["il"].configure(text=SPIN[0], text_color=YEL)
                    r["tx"].configure(text=text or r["name"], text_color=WHITE, font=(HEAVY, 15))
                    r["bar"].grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 4))
                    r["bar"].stop()
                    if i == 1:
                        r["bar"].configure(mode="determinate")
                        r["bar"].set(0)
                    else:
                        r["bar"].configure(mode="indeterminate")
                        r["bar"].start()
                else:
                    r["bar"].stop()
                    r["bar"].grid_forget()
                    r["ic"].configure(fg_color="#DDD")
                    r["il"].configure(text="")
                    r["tx"].configure(text=r["name"], text_color="#999", font=("Segoe UI Semibold", 15))
                    r["pc"].configure(text="")
            if idx < len(STAGES):
                self.p_top.configure(text=f"{self._prefix}PASO {idx + 1} DE {len(STAGES)}")
                self.p_title.configure(text=text or STAGES[idx])

        def tick(self):
            if self.busy and 0 <= self.stage < len(STAGES):
                self.spin_i = (self.spin_i + 1) % len(SPIN)
                self.rows[self.stage]["il"].configure(text=SPIN[self.spin_i])
            self.after(120, self.tick)

        def card(self, parent):
            return ctk.CTkFrame(parent, fg_color="#151B21", border_color="#303942", border_width=1, corner_radius=12)

        def badge(self, parent, n):
            f = ctk.CTkFrame(parent, width=32, height=32, corner_radius=16, fg_color=YEL)
            f.pack_propagate(False)
            ctk.CTkLabel(f, text=n, text_color=BLACK, font=(HEAVY, 14), fg_color="transparent").pack(expand=True)
            return f

        def make_platform_logo(self, site):
            from PIL import Image, ImageDraw, ImageFont
            size = 112
            palette = {
                "YOUTUBE": ("#FF0033", "▶", "#FFFFFF"),
                "INSTAGRAM": ("#C13584", "◎", "#FFFFFF"),
                "TIKTOK": ("#111111", "♪", "#25F4EE"),
                "X": ("#000000", "𝕏", "#FFFFFF"),
                "PINTEREST": ("#BD081C", "P", "#FFFFFF"),
                "LINK": ("#252C33", "↗", YEL),
            }
            bg, mark, fg = palette.get(site, palette["LINK"])
            im = Image.new("RGBA", (size, size), bg)
            d = ImageDraw.Draw(im)
            try:
                font = ImageFont.truetype("C:/Windows/Fonts/seguisym.ttf", 66)
            except Exception:
                try: font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 66)
                except Exception: font = ImageFont.load_default()
            box = d.textbbox((0, 0), mark, font=font, stroke_width=0)
            x = (size - (box[2] - box[0])) / 2 - box[0]
            y = (size - (box[3] - box[1])) / 2 - box[1] - 3
            if site == "YOUTUBE":
                d.rounded_rectangle((18, 29, 94, 83), radius=15, fill="#FFFFFF")
                d.polygon([(48, 39), (48, 73), (75, 56)], fill=bg)
            elif site == "INSTAGRAM":
                d.rounded_rectangle((24, 24, 88, 88), radius=19, outline="#FFFFFF", width=7)
                d.ellipse((41, 41, 71, 71), outline="#FFFFFF", width=7)
                d.ellipse((70, 32, 80, 42), fill="#FFFFFF")
            elif site == "PINTEREST":
                d.ellipse((18, 18, 94, 94), fill="#FFFFFF")
                d.text((x, y-1), "P", font=font, fill=bg)
            else:
                d.text((x, y), mark, font=font, fill=fg)
            return ctk.CTkImage(light_image=im, dark_image=im, size=(56, 56))

        def on_url(self):
            url = self.url.get().strip()
            site = site_name(url) if url else "LINK"
            icons = {"YOUTUBE": ("▶", "YouTube"), "INSTAGRAM": ("◎", "Instagram"), "TIKTOK": ("♪", "TikTok"), "X": ("𝕏", "X / Twitter"), "PINTEREST": ("ℙ", "Pinterest"), "LINK": ("↗", "Plataforma")}
            ico, label = icons.get(site, ("↗", "Plataforma"))
            self.chip.configure(text=f"{ico}  {label}")
            if hasattr(self, "platform_icon"):
                self.platform_icon.configure(image=self.make_platform_logo(site), text="")
                self.preview_title.configure(text="Cargando información…" if url else "Esperando un enlace")
                self.preview_meta.configure(text=f"{label} · enlace recibido · preparando vista previa" if url else "Pegá un enlace para detectar plataforma y detalles")
                self.thumbnail_label.configure(image=None, text="Cargando…" if url else "Sin enlace")
                self.thumbnail_image = None
                if self._meta_job:
                    try: self.after_cancel(self._meta_job)
                    except Exception: pass
                if url and clean_url(url):
                    self._meta_job = self.after(100, lambda u=url: self.fetch_metadata(u))
            if self._last_clip_url != url:
                self._last_clip_url = url
                if hasattr(self, "v_clip") and self.v_clip.get():
                    self.v_clip.set(False)
                    try:
                        self.clip_start.delete(0, "end")
                        self.clip_end.delete(0, "end")
                    except Exception:
                        pass
            yt_long = site == "YOUTUBE" and "/shorts/" not in url.lower() and "/live/" not in url.lower()
            if hasattr(self, "clip_toggle") and hasattr(self, "clip_frame"):
                if yt_long:
                    self.clip_toggle.grid()
                    self.clip_frame.grid()
                else:
                    self.clip_toggle.grid_remove()
                    self.clip_frame.grid_remove()
                    self.v_clip.set(False)

        def fetch_metadata(self, url):
            def worker():
                try:
                    import yt_dlp
                    ensure_temp_dir()
                    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
                            "socket_timeout": 10, "retries": 0, "extractor_retries": 0,
                            "paths": {"temp": str(TEMP_DIR)}}
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                    self._metadata_cache[url] = info
                    title = str(info.get("title") or "Contenido detectado")
                    author = str(info.get("uploader") or info.get("channel") or info.get("creator") or "Autor no disponible")
                    description = str(info.get("description") or "").strip().replace("\n", " ")
                    description = re.sub(r"\s+", " ", description)
                    if len(description) > 180:
                        description = description[:177].rstrip() + "…"
                    dur = info.get("duration")
                    duration = f"{int(dur)//60}:{int(dur)%60:02d}" if dur else "Duración no disponible"
                    width, height = info.get("width"), info.get("height")
                    resolution = f"{width} × {height}" if width and height else "Resolución disponible al descargar"
                    ext = str(info.get("ext") or "media").upper()
                    meta = f"@{author.lstrip('@')}  ·  {duration}  ·  {resolution}  ·  {ext}"
                    if description:
                        meta += "\n" + description
                    thumb_data = None
                    # TikTok puede devolver la portada en `thumbnail`, en `thumbnails`
                    # o como `cover_image_url`; no todos los extractores rellenan el mismo campo.
                    thumb_candidates = []
                    for candidate in (
                        info.get("thumbnail"),
                        info.get("cover_image_url"),
                        info.get("origin_cover"),
                        info.get("dynamic_cover"),
                    ):
                        if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                            thumb_candidates.append(candidate)
                    thumb_list = info.get("thumbnails") or []
                    if isinstance(thumb_list, list):
                        # Prefer the best available thumbnail first; yt-dlp normally orders
                        # these by preference, so reverse iteration tries the latest/best variant.
                        for item in reversed(thumb_list):
                            if isinstance(item, dict):
                                candidate = item.get("url")
                                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                                    thumb_candidates.append(candidate)
                    # Keep order but avoid retrying identical CDN URLs.
                    thumb_candidates = list(dict.fromkeys(thumb_candidates))
                    if thumb_candidates:
                        try:
                            from urllib.request import Request, urlopen
                            for thumb_url in thumb_candidates:
                                try:
                                    req = Request(thumb_url, headers={
                                        "User-Agent": "Mozilla/5.0",
                                        "Referer": "https://www.tiktok.com/",
                                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                    })
                                    with urlopen(req, timeout=5) as response:
                                        data = response.read(2_500_000)
                                    if data:
                                        thumb_data = data
                                        break
                                except Exception as thumb_exc:
                                    log(f"thumbnail candidate {url} ({thumb_url[:100]}): {thumb_exc!r}")
                        except Exception as thumb_exc:
                            log(f"thumbnail {url}: {thumb_exc!r}")
                    self.after(0, lambda: self.apply_metadata(url, title, meta, thumb_data, "Miniatura cargada" if thumb_data else "No se pudo cargar la miniatura"))
                except Exception as exc:
                    log(f"metadata yt-dlp {url}: {exc!r}\n{traceback.format_exc()}")
                    if "instagram.com/p/" in url.lower() or "pinterest." in url.lower() or "pin.it/" in url.lower():
                        try:
                            entries = gallery_dl_extract(url, self.cfg)
                            first = entries[0]
                            title = str(first.get("description") or first.get("post_id") or "Publicación de imágenes")
                            author = str(first.get("username") or first.get("owner") or "Instagram")
                            thumb_data = None
                            thumb_url = (first.get("_indiedl_url") or first.get("_url")
                                         or first.get("url") or first.get("file_url") or first.get("gdl_file_url"))
                            if thumb_url:
                                try:
                                    from urllib.request import Request, urlopen
                                    req = Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                                    with urlopen(req, timeout=8) as response:
                                        thumb_data = response.read(2_500_000)
                                except Exception as thumb_exc:
                                    log(f"gallery thumbnail {url}: {thumb_exc!r}")
                            meta = f"{author}  ·  {len(entries)} imagen(es)  ·  Original"
                            self.after(0, lambda: self.apply_metadata(url, title, meta, thumb_data, "Miniatura cargada" if thumb_data else "No se pudo cargar la miniatura"))
                            return
                        except Exception as gallery_exc:
                            log(f"metadata gallery-dl {url}: {gallery_exc!r}")
                    self.after(0, lambda: self.apply_metadata(url, "No se pudieron cargar los detalles", "El enlace se recibió correctamente. La descarga se puede intentar igualmente; revisá la conexión o el registro.", None, "Vista previa no disponible"))
            threading.Thread(target=worker, daemon=True).start()

        def apply_metadata(self, url, title, meta, thumb_data=None, thumb_status=None):
            if self.url.get().strip() != url:
                return
            self.preview_title.configure(text=title)
            self.preview_meta.configure(text=meta)
            if thumb_data:
                try:
                    import io
                    from PIL import Image
                    im = Image.open(io.BytesIO(thumb_data)).convert("RGB")
                    im.thumbnail((180, 100), Image.Resampling.LANCZOS)
                    self.thumbnail_image = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
                    self.thumbnail_label.configure(image=self.thumbnail_image, text="")
                except Exception as exc:
                    log(f"thumbnail render {url}: {exc!r}")
                    self.thumbnail_label.configure(image=None, text="Vista previa no disponible")
            else:
                self.thumbnail_label.configure(image=None, text=thumb_status or "Sin miniatura")

        def configure_cookies(self):
            win = ctk.CTkToplevel(self)
            win.title("IndieDL · Sesión de Instagram")
            win.geometry("500x300")
            win.resizable(False, False)
            win.transient(self)
            win.grab_set()
            win.configure(fg_color=BLACK)
            ctk.CTkLabel(win, text="SESIÓN DEL NAVEGADOR", font=(HEAVY, 18), text_color=YEL).pack(
                anchor="w", padx=22, pady=(20, 6))
            ctk.CTkLabel(win, text="Elegí dónde tenés iniciada la sesión de Instagram.\nEn una PC nueva, iniciá sesión primero en ese navegador.",
                         font=("Segoe UI", 12), text_color=GRAY, justify="left").pack(anchor="w", padx=22, pady=(0, 14))
            labels = {"Auto (recomendado)": "auto", "Zen Browser": "zen", "Firefox": "firefox",
                      "Google Chrome": "chrome", "Microsoft Edge": "edge", "Brave": "brave"}
            current = str(self.cfg.get("cookies_browser", "auto") or "auto").lower()
            reverse = {v: k for k, v in labels.items()}
            selected = ctk.StringVar(value=reverse.get(current, "Auto (recomendado)"))
            menu = ctk.CTkOptionMenu(win, values=list(labels), variable=selected, height=40,
                                     fg_color="#252C33", button_color="#252C33", text_color=WHITE,
                                     dropdown_fg_color="#20272E", font=("Segoe UI Semibold", 13))
            menu.pack(fill="x", padx=22, pady=(0, 18))
            status = ctk.CTkLabel(win, text="", text_color=GRAY, font=("Segoe UI", 11), wraplength=450, justify="left")
            status.pack(fill="x", padx=22, pady=(0, 10))
            buttons = ctk.CTkFrame(win, fg_color="transparent")
            buttons.pack(fill="x", padx=22, pady=(0, 18))
            def save_choice():
                choice = labels.get(selected.get(), "auto")
                self.cfg["cookies_browser"] = choice
                save_cfg(self.cfg)
                try:
                    browser, profile = cookie_source(self.cfg)
                    status.configure(text=(f"Guardado. Se usará {browser} con perfil detectado." if profile else
                                           f"Guardado. Se usará {browser or 'acceso sin sesión'} con detección automática."), text_color=GREEN)
                    log(f"Preferencia de cookies guardada: {choice}; navegador resuelto={browser or 'ninguno'}; perfil_detectado={'sí' if profile else 'no'}")
                except Exception as exc:
                    status.configure(text=f"Preferencia guardada, pero falta configurar la sesión: {exc}", text_color=RED)
                self.after(1800, win.destroy)
            ctk.CTkButton(buttons, text="GUARDAR", height=38, fg_color=YEL, hover_color=YEL_H,
                          text_color=BLACK, font=(HEAVY, 12), command=save_choice).pack(side="right")
            ctk.CTkButton(buttons, text="CANCELAR", height=38, fg_color="#252C33", hover_color="#343D46",
                          text_color=WHITE, font=(HEAVY, 12), command=win.destroy).pack(side="right", padx=(0, 8))

        def set_mode(self, m):
            self.cur_mode = m
            on = dict(fg_color=YEL, hover_color=YEL_H, text_color=BLACK)
            off = dict(fg_color=BLACK, hover_color="#222", text_color=WHITE)
            self.b_video.configure(**(on if m == "video" else off))
            self.b_audio.configure(**(on if m == "audio" else off))
            self.b_image.configure(**(on if m == "image" else off))
            if m == "video":
                self.l_q.configure(text="✦ Calidad")
                self.menu.configure(values=VIDEO_Q)
                self.menu.set(self.cfg.get("video_q") if self.cfg.get("video_q") in VIDEO_Q else VIDEO_Q[0])
            elif m == "audio":
                self.l_q.configure(text="♫ Formato")
                self.menu.configure(values=AUDIO_F)
                self.menu.set(self.cfg.get("audio_fmt") if self.cfg.get("audio_fmt") in AUDIO_F else AUDIO_F[0])
            else:
                self.l_q.configure(text="▧ Tipo de imagen")
                self.menu.configure(values=IMAGE_F)
                self.menu.set("Original")

        def begin_image_selection(self, url, folder, quality):
            if self._image_dialog is not None:
                try:
                    self._image_dialog.lift()
                    return
                except Exception:
                    self._image_dialog = None
            self.msg.configure(text="Analizando imágenes del carrusel…")

            def worker():
                try:
                    entries = gallery_dl_extract(url, self.cfg)
                    info = {"title": str(entries[0].get("description") or entries[0].get("post_id") or "Publicación de imágenes"),
                            "uploader": str(entries[0].get("username") or entries[0].get("owner") or "Instagram"),
                            "entries": entries}
                    normalized = []
                    for idx, entry in enumerate(entries, start=1):
                        direct = (entry.get("_indiedl_url") or entry.get("_url") or entry.get("url")
                                  or entry.get("file_url") or entry.get("gdl_file_url"))
                        filename = str(entry.get("filename") or entry.get("_filename") or "")
                        ext = str(entry.get("extension") or entry.get("_extension") or "jpg")
                        normalized.append({"id": str(entry.get("post_id") or entry.get("id") or idx),
                                           "title": str(entry.get("description") or f"Imagen {idx} · {filename or ext}"),
                                           "thumbnail": direct, "url": direct, "extension": ext,
                                           "gallery_index": idx})
                    self.after(0, lambda: self.show_image_selector(url, folder, quality, info, normalized))
                except Exception as exc:
                    msg = str(exc).replace("ERROR: ", "")[:300]
                    log(f"image selection {url}: {exc!r}")
                    self.after(0, lambda m=msg: self.image_selection_error(m))

            threading.Thread(target=worker, daemon=True).start()

        def image_selection_error(self, message):
            self.msg.configure(text="No se pudo leer el carrusel. Revisá la sesión/cookies de Instagram.")
            messagebox.showerror("IndieDL · Imágenes", message or "No se encontraron imágenes accesibles.", parent=self)
            self._image_dialog = None

        def show_image_selector(self, url, folder, quality, info, entries):
            self.msg.configure(text="")
            win = ctk.CTkToplevel(self)
            self._image_dialog = win
            is_carousel = len(entries) > 1
            win.title("IndieDL · Seleccionar imágenes" if is_carousel else "IndieDL · Imagen individual")
            win.geometry("700x620" if is_carousel else "620x430")
            win.minsize(560, 420)
            win.transient(self)
            win.grab_set()
            win.configure(fg_color=BLACK)
            heading = "CARRUSEL DE IMÁGENES" if is_carousel else "IMAGEN INDIVIDUAL"
            ctk.CTkLabel(win, text=heading, font=(HEAVY, 18), text_color=YEL).pack(anchor="w", padx=18, pady=(16, 4))
            instruction = (f"{len(entries)} imágenes detectadas. Elegí una o varias, o descargá todas."
                           if is_carousel else "Se detectó una imagen. Revisá los datos y descargala en calidad original disponible.")
            ctk.CTkLabel(win, text=instruction,
                         font=("Segoe UI", 12), text_color=GRAY).pack(anchor="w", padx=18, pady=(0, 12))
            scroll = ctk.CTkScrollableFrame(win, fg_color="#10151A", corner_radius=10)
            scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))
            vars_ = []
            thumb_refs = []
            self._carousel_thumb_refs = thumb_refs
            for idx, entry in enumerate(entries, start=1):
                row = ctk.CTkFrame(scroll, fg_color="#1A2026", corner_radius=8)
                row.pack(fill="x", padx=4, pady=4)
                var = ctk.BooleanVar(value=True)
                vars_.append(var)
                if is_carousel:
                    cb = ctk.CTkCheckBox(row, text=f"Imagen {idx}", variable=var, text_color=WHITE,
                                         fg_color=YEL, hover_color=YEL_H, checkmark_color=BLACK,
                                         font=("Segoe UI Semibold", 12), width=120)
                    cb.pack(side="left", padx=10, pady=10)
                else:
                    ctk.CTkLabel(row, text="▧ FOTO", text_color=YEL, font=(HEAVY, 12), width=120).pack(side="left", padx=10, pady=10)
                thumb = ctk.CTkLabel(row, text="Vista previa no disponible", width=150, height=82,
                                     fg_color="#252C33", text_color=GRAY, corner_radius=6)
                thumb.pack(side="left", padx=(0, 10), pady=8)
                title = str(entry.get("title") or entry.get("description") or entry.get("id") or f"Elemento {idx}")
                ctk.CTkLabel(row, text=title[:100], text_color=WHITE, anchor="w", justify="left",
                             wraplength=300).pack(side="left", fill="x", expand=True, padx=(0, 10))
                thumb_url = (entry.get("thumbnail") or entry.get("_indiedl_url") or entry.get("_url")
                             or entry.get("url") or entry.get("file_url"))
                if not thumb_url:
                    thumbs = entry.get("thumbnails") or []
                    if thumbs:
                        thumb_url = thumbs[-1].get("url")
                if thumb_url:
                    def load_thumb(target=thumb, src=thumb_url, ref_idx=idx):
                        try:
                            from urllib.request import Request, urlopen
                            import io
                            from PIL import Image
                            req = Request(src, headers={"User-Agent": "Mozilla/5.0"})
                            with urlopen(req, timeout=8) as resp:
                                data = resp.read(1_500_000)
                            im = Image.open(io.BytesIO(data)).convert("RGB")
                            im.thumbnail((150, 82), Image.Resampling.LANCZOS)
                            image = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
                            def apply():
                                if target.winfo_exists():
                                    target.configure(image=image, text="")
                                    thumb_refs.append(image)
                            self.after(0, apply)
                        except Exception as exc:
                            log(f"carousel thumbnail {ref_idx}: {exc!r}")
                    threading.Thread(target=load_thumb, daemon=True).start()

            footer = ctk.CTkFrame(win, fg_color="transparent")
            footer.pack(fill="x", padx=16, pady=(0, 16))
            def finish(all_items=False):
                if not win.winfo_exists():
                    return
                chosen = list(range(1, len(entries) + 1)) if all_items else [i for i, v in enumerate(vars_, start=1) if v.get()]
                if not chosen:
                    messagebox.showwarning("IndieDL", "Seleccioná al menos una imagen.", parent=win)
                    return
                self._image_indices = None if all_items or len(chosen) == len(entries) else chosen
                self._image_selection_ready = True
                self._skip_folder_once = True
                self._folder_explicit = True
                self.folder.delete(0, "end")
                self.folder.insert(0, folder)
                self._image_dialog = None
                win.grab_release()
                win.destroy()
                self.start()
            if is_carousel:
                ctk.CTkButton(footer, text="DESCARGAR TODAS", fg_color=YEL, hover_color=YEL_H,
                              text_color=BLACK, font=(HEAVY, 12), command=lambda: finish(True)).pack(side="left", expand=True, fill="x", padx=(0, 6))
                ctk.CTkButton(footer, text="DESCARGAR SELECCIÓN", fg_color="#252C33", hover_color="#343D46",
                              text_color=WHITE, font=(HEAVY, 12), command=lambda: finish(False)).pack(side="left", expand=True, fill="x", padx=(6, 0))
            else:
                ctk.CTkButton(footer, text="DESCARGAR IMAGEN", fg_color=YEL, hover_color=YEL_H,
                              text_color=BLACK, font=(HEAVY, 12), command=lambda: finish(False)).pack(side="left", expand=True, fill="x")
            win.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "_image_dialog", None), win.destroy()))

        def pick(self):
            d = filedialog.askdirectory(initialdir=self.folder.get() or None, parent=self)
            if d:
                self.folder.delete(0, "end")
                self.folder.insert(0, os.path.normpath(d))
                self._folder_explicit = True

        def open_dir(self, p):
            try:
                os.startfile(p)
            except Exception:
                pass

        def show_panel(self, which):
            self.panel = which
            self.hist.pack_forget()
            self.live.pack_forget()
            tgt = self.live if which == "live" else self.hist
            tgt.pack(fill="both", expand=True, padx=8, pady=8)
            self.r_title.configure(text="En vivo" if which == "live" else "Historial")
            sel = dict(fg_color=YEL, hover_color=YEL_H, text_color=BLACK)
            uns = dict(fg_color="#222", hover_color="#333", text_color=WHITE)
            self.b_live.configure(**(sel if which == "live" else uns))
            self.b_hist.configure(**(sel if which == "hist" else uns))

        def add_log(self, text):
            t = int(time.time() - self.t0)
            f = ctk.CTkFrame(self.live, fg_color="transparent")
            f.pack(fill="x")
            ctk.CTkLabel(f, text=f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}", font=("Consolas", 10),
                         text_color="#777", anchor="w").pack(fill="x", padx=8, pady=(8, 0))
            ctk.CTkLabel(f, text=text, font=("Segoe UI", 12), text_color=WHITE, anchor="w", justify="left",
                         wraplength=240).pack(fill="x", padx=8, pady=(0, 8))
            ctk.CTkFrame(f, fg_color="#222", height=1, corner_radius=0).pack(fill="x")
            self.after(30, lambda: self.live._parent_canvas.yview_moveto(1.0))

        def render_hist(self):
            for w in self.hist.winfo_children():
                w.destroy()
            items = self.cfg.get("history", [])
            if not items:
                ctk.CTkLabel(self.hist, text="Tus descargas aparecerán acá", text_color="#777",
                             font=("Segoe UI", 12), wraplength=240).pack(pady=60)
                return
            for it in items:
                f = ctk.CTkFrame(self.hist, fg_color="#151B21", border_width=1, border_color="#303942", corner_radius=10, cursor="hand2")
                f.pack(fill="x", pady=4)
                t = it.get("title", "")
                l1 = ctk.CTkLabel(f, text=(t[:46] + "...") if len(t) > 46 else t, text_color=WHITE,
                                  font=("Segoe UI Semibold", 12), anchor="w", justify="left", wraplength=240)
                l1.pack(fill="x", padx=10, pady=(8, 0))
                site_icons = {"YOUTUBE":"▶", "INSTAGRAM":"◎", "TIKTOK":"♪", "X":"𝕏", "PINTEREST":"ℙ", "LINK":"↗"}
                icon = site_icons.get(it.get("site", "LINK"), "↗")
                txt = f'{icon}  {it.get("mode", "").upper()}  ·  {it.get("site", "")}  ·  {it.get("when", "")}'
                l2 = ctk.CTkLabel(f, text=txt, text_color=GRAY, font=("Segoe UI", 10), anchor="w", justify="left")
                l2.pack(fill="x", padx=10, pady=(0, 8))
                folder = it.get("folder", "")
                if folder:
                    for w in (f, l1, l2):
                        w.bind("<Button-1>", lambda e, p=folder: self.open_dir(p))

        def start(self):
            if self.busy:
                return
            if getattr(self, 'batch_mode', False):
                self.start_batch()
                return
                
            url = self.url.get().strip()
            if not url:
                self.msg.configure(text="Pegá un enlace primero.")
                return
            self.msg.configure(text="")

            mode = self.cur_mode
            folder = self.folder.get().strip()
            quality = self.menu.get()

            if not folder:
                self.msg.configure(text="Elegí una carpeta de destino.")
                return
            
            clip = None
            if self.v_clip.get():
                s = parse_timestamp(self.clip_start.get())
                e = parse_timestamp(self.clip_end.get())
                if s is None or e is None or e <= s:
                    self.msg.configure(text="Recorte inválido. Usá formato MM:SS o HH:MM:SS.")
                    return
                clip = (s, e)

            self.cfg["last_dir"] = folder
            self.cfg["video_q"] = self.menu.get() if mode == "video" else self.cfg.get("video_q", "Mejor")
            self.cfg["audio_fmt"] = self.menu.get() if mode == "audio" else self.cfg.get("audio_fmt", "mp3")
            self.cfg["ask_folder"] = self.v_ask.get()
            self.cfg["close_when_done"] = self.v_close.get()
            self.cfg["pcm_resolve"] = self.v_pcm.get()
            save_cfg(self.cfg)

            if mode == "image":
                if self._image_selection_ready:
                    self._image_selection_ready = False
                    self.start_dl(url, mode, folder, quality, clip, self._image_indices)
                else:
                    self.begin_image_selection(url, folder, quality)
                return

            self.start_dl(url, mode, folder, quality, clip, None)

        def start_batch(self):
            items = self.batch
            folder = self.folder.get().strip()
            quality = self.menu.get()
            if not folder:
                self.msg.configure(text="Elegí una carpeta de destino.")
                return
            
            self.busy = True
            self.form.pack_forget()
            self.pv.pack(fill="both", expand=True)
            self.show_buttons("run")
            self.btn.configure(state="disabled", text="DESCARGANDO LOTE...")
            self.t0 = time.time()
            self.set_stage(0, "Conectando…")
            for key in self.stat:
                self.stat[key].configure(text="-")
            self.p_msg.configure(text="")
            self.cancel.clear()

            def worker():
                success = 0
                total = len(items)
                for idx, item in enumerate(items):
                    if self.cancel.is_set():
                        break
                    u = item["url"]
                    title = item.get("title", "")
                    self.q.put(("log", f"[{idx+1}/{total}] Iniciando: {title or u}"))
                    try:
                        run_download(u, self.cur_mode, folder, self.cfg, self.q, quality, self.cancel)
                        success += 1
                    except Exception as e:
                        self.q.put(("log", f"Error en {title or u}: {e}"))
                self.q.put(("done", folder, f"Lote finalizado: {success}/{total} completados."))
            
            threading.Thread(target=worker, daemon=True).start()

        def start_dl(self, url, mode, folder, quality, clip, image_indices):
            self.busy = True
            self.show_buttons("run")
            self.form.pack_forget()
            self.pv.pack(fill="both", expand=True)
            self.btn.configure(state="disabled", text="DESCARGANDO...")
            self.t0 = time.time()
            self.set_stage(0, "Conectando…")
            for key in self.stat:
                self.stat[key].configure(text="-")
            self.p_msg.configure(text="")
            self.cancel.clear()

            def worker():
                try:
                    run_download(url, mode, folder, self.cfg, self.q, quality, self.cancel, clip, image_indices)
                except Exception as e:
                    self.q.put(("err", str(e)))
            threading.Thread(target=worker, daemon=True).start()

        def enter_batch(self, batch):
            self.batch = batch
            self.batch_mode = True
            self._prefix = f"[LOTE {len(batch)}] "
            self.url.configure(state="disabled")
            self.url.delete(0, "end")
            self.url.insert(0, f"Cola de {len(batch)} elementos lista para descargar.")
            self.b_video.configure(state="disabled")
            self.b_audio.configure(state="disabled")
            self.b_image.configure(state="disabled")
            self.v_clip.set(False)
            self.clip_frame.grid_remove()
            self.clip_toggle.grid_remove()

            self.btn.configure(text=f"⬇  DESCARGAR LOTE ({len(batch)})")

        def apply_clip(self, clip):
            self.v_clip.set(True)
            self.clip_start.delete(0, "end")
            self.clip_start.insert(0, fmt_hms(clip[0]))
            self.clip_end.delete(0, "end")
            self.clip_end.insert(0, fmt_hms(clip[1]))
            if not self.clip_toggle.winfo_ismapped():
                self.clip_toggle.grid()
                self.clip_frame.grid()

        def load_last_batch(self):
            pass

        def refresh_last_btn(self):
            pass

        def back(self):
            self.busy = False
            self.pv.pack_forget()
            self.form.pack(fill="both", expand=True)
            self.show_buttons("run")
            self.btn.configure(state="normal", text="⬇  DESCARGAR")
            self.set_stage(-1)
            self.msg.configure(text="")
            self.url.focus()

        def poll(self):
            try:
                while True:
                    ev = self.q.get_nowait()
                    kind = ev[0]
                    if kind == "stage":
                        _, idx, text = ev
                        self.set_stage(idx, text)
                    elif kind == "prog":
                        _, p, sp, eta, dl, tot, n, total = ev
                        if 0 <= self.stage < len(self.rows):
                            bar = self.rows[self.stage]["bar"]
                            if self.stage == 1 and bar.cget("mode") == "determinate":
                                bar.set(p)
                        self.stat["sp"].configure(text=fb(sp) + "/s" if sp else "-")
                        self.stat["eta"].configure(text=ft(eta) if eta else "-")
                        self.stat["sz"].configure(text=fb(tot) if tot else fb(dl))
                        self.stat["fi"].configure(text=f"{n}/{total}" if total else "-")
                    elif kind == "log":
                        self.add_log(ev[1])
                    elif kind == "note":
                        self.p_msg.configure(text=ev[1], text_color=YEL)
                    elif kind == "done":
                        _, folder, title = ev
                        self.finish(folder, title)
                    elif kind == "err":
                        self.finish_error(ev[1])
            except queue.Empty:
                pass
            self.after(100, self.poll)

        def finish(self, folder, title):
            self.busy = False
            self.set_stage(3, "Finalizando")
            for i in range(4):
                r = self.rows[i]
                r["bar"].stop()
                r["bar"].grid_forget()
                r["ic"].configure(fg_color=YEL)
                r["il"].configure(text="✓", text_color=BLACK)
                r["tx"].configure(text_color=WHITE)
            self.b_open.configure(state="normal")
            self.show_buttons("done")
            self.btn.configure(state="normal", text="⬇  DESCARGAR")
            
            hist = self.cfg.get("history", [])
            site = site_name(self.url.get())
            hist.insert(0, {"title": title, "site": site, "when": time.strftime("%d/%m/%Y %H:%M"), "mode": self.cur_mode, "folder": folder})
            self.cfg["history"] = hist[:50]
            save_cfg(self.cfg)
            self.render_hist()
            
            self.p_title.configure(text="¡Completado!")
            self.p_sub.configure(text=title)
            self.p_msg.configure(text="", text_color=RED)
            
            if self.cfg.get("close_when_done"):
                time.sleep(2)
                self.destroy()

        def finish_error(self, err):
            self.busy = False
            self.show_buttons("done")
            self.btn.configure(state="normal", text="⬇  DESCARGAR")
            self.p_msg.configure(text=err, text_color=RED)
            if 0 <= self.stage < len(self.rows):
                self.rows[self.stage]["ic"].configure(fg_color=RED)
                self.rows[self.stage]["il"].configure(text="✕", text_color=WHITE)
                self.rows[self.stage]["bar"].stop()
            self.p_title.configure(text="Error")

    # -------- ARRANQUE DE LA APLICACIÓN --------
    uri = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg = load_cfg()
    
    batch = None
    mode, url, clip = "video", "", None
    
    if uri:
        b = parse_batch(uri)
        if b:
            batch = b
        else:
            p = parse_uri(uri)
            if p:
                mode, url = p
                clip = parse_clip(uri)
    
    app = App(mode, url, batch, clip)
    app.mainloop()

if __name__ == "__main__":
    # 1. Auto-registrar el protocolo ytdl:// en Windows
    if os.name == "nt":
        try:
            register()
            log("Protocolo ytdl:// auto-registrado correctamente.")
        except Exception as e:
            log(f"Error al auto-registrar protocolo: {e}")

    # 2. Si el instalador lo llama solo para registrar, salir sin abrir la ventana
    if "--register-only" in sys.argv:
        sys.exit(0)

    # 3. Abrir la interfaz gráfica
    build_app()
