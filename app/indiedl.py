"""Indie Now DL - descargador para Windows con integración de navegador."""
import json, os, queue, re, shutil, subprocess, sys, threading, time, traceback, tempfile, uuid
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
    here = Path(__file__).resolve()
    launcher = here.with_name("launcher.pyw")
    if launcher.exists():
        # El lanzador corre con el pythonw del Python BASE (no el del venv): asi
        # no hereda una etiqueta de integridad baja y puede corregirla.
        base = Path(sys.base_prefix) / "pythonw.exe"
        host = base if base.exists() else pyw
        cmd = f'"{host}" "{launcher}" "%1"'
    else:
        cmd = f'"{pyw}" "{here}" "%1"'
    base_key = r"Software\Classes\ytdl"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_key) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:ytdl Protocol")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_key + r"\shell\open\command") as k:
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

def format_seconds(value):
    return f"{float(value):.3f}".rstrip("0").rstrip(".")

def media_duration(ff, path):
    info = probe(ff, path)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    if not match:
        return None
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))

def enforce_clip(ff, path, section, mode, quality, q):
    """Verify yt-dlp actually returned the requested range; cut locally if it didn't."""
    start, end = section
    wanted = max(0.0, float(end) - float(start))
    duration = media_duration(ff, path)
    if duration is not None and duration <= wanted + 1.25:
        q.put(("log", f"Duración del recorte verificada: {format_seconds(duration)} s"))
        return path

    q.put(("log", "yt-dlp devolvió el archivo completo; aplicando el recorte In/Out con FFmpeg"))
    source_base, source_ext = os.path.splitext(path)
    if mode == "video":
        target = path if source_ext.lower() == ".mp4" else source_base + " [recorte].mp4"
        temporary = os.path.splitext(target)[0] + ".indiedl_clip.tmp.mp4"
        encoders = [
            ("h264_nvenc", ["-preset", "p4", "-cq", "20"], "GPU"),
            ("libx264", ["-preset", "veryfast", "-crf", "20"], "CPU"),
        ]
        last_error = ""
        for encoder, quality_args, device in encoders:
            if device == "CPU":
                q.put(("log", "NVENC no está disponible para el recorte; usando CPU"))
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass
            cmd = [ff, "-y", "-i", path, "-ss", format_seconds(start),
                   "-t", format_seconds(wanted), "-map", "0:v:0?", "-map", "0:a?",
                   "-c:v", encoder, *quality_args, "-profile:v", "high", "-pix_fmt", "yuv420p",
                   "-fps_mode", "passthrough",
                   "-c:a", "aac", "-b:a", "192k",
                   "-movflags", "+faststart", temporary]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                        errors="replace", creationflags=NO_WINDOW, timeout=1800)
            except Exception as exc:
                last_error = str(exc)
                continue
            last_error = (result.stderr or "")[-700:]
            if result.returncode == 0 and os.path.isfile(temporary) and os.path.getsize(temporary) > 0:
                clipped_duration = media_duration(ff, temporary)
                if clipped_duration is None or clipped_duration <= wanted + 1.25:
                    break
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        else:
            raise RuntimeError("No se pudo verificar ni aplicar el recorte In/Out. " + last_error[-300:])
    else:
        target = path
        temporary = source_base + ".indiedl_clip.tmp" + source_ext
        codec_args = {
            ".mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
            ".wav": ["-c:a", "pcm_s16le"],
            ".m4a": ["-c:a", "aac", "-b:a", "256k"],
        }.get(source_ext.lower(), ["-c:a", "copy"])
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
        cmd = [ff, "-y", "-ss", format_seconds(start), "-i", path,
               "-t", format_seconds(wanted), "-map", "0:a:0", "-vn", *codec_args, temporary]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", creationflags=NO_WINDOW, timeout=1800)
        if result.returncode != 0 or not os.path.isfile(temporary) or os.path.getsize(temporary) <= 0:
            raise RuntimeError("No se pudo aplicar el recorte al audio. " + (result.stderr or "")[-300:])
        clipped_duration = media_duration(ff, temporary)
        if clipped_duration is not None and clipped_duration > wanted + 1.25:
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise RuntimeError("FFmpeg no pudo verificar la duración del recorte de audio.")

    for intento in range(15):
        try:
            os.replace(temporary, target)
            break
        except (PermissionError, OSError) as exc:
            if intento == 14:
                raise RuntimeError(f"No se pudo guardar el recorte final. Bloqueo: {exc}") from exc
            time.sleep(0.5)

    if os.path.abspath(path) != os.path.abspath(target):
        try:
            os.remove(path)
        except OSError:
            pass
    q.put(("log", f"Recorte In/Out aplicado: {format_seconds(start)}–{format_seconds(end)} s ({device if mode == 'video' else 'audio'})"))
    return target

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
    p = shutil.which("ffmpeg")
    if p:
        return p
    candidates = [
        APP_DIR / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
        APP_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
        Path(sys.executable).resolve().parent / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
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
    cmd = [ff, "-y", "-copyts", "-start_at_zero", "-i", src,
           "-map", "0:v:0?", "-map", "0:a?",
           "-c:v", "copy",
           "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "256k", "-ar", "48000",
           "-map_metadata", "0", "-map_chapters", "0",
           "-movflags", "+faststart", dst]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=900)
    except Exception as e:
        q.put(("log", "No pude normalizar el audio: " + str(e)))
        return src
    
    def safe_replace(src_path, dst_path):
        for _ in range(15):
            try:
                os.replace(src_path, dst_path)
                return True
            except PermissionError:
                time.sleep(0.5)
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
        for sync in (["-fps_mode", "passthrough"], []):
            try:
                if os.path.exists(dst):
                    os.remove(dst)
            except OSError:
                pass
            cmd = [ff, "-y", "-copyts", "-start_at_zero", "-i", src,
                   "-map", "0:v:0", "-map", "0:a?",
                   "-c:v", encoder, *quality_args, "-profile:v", "high",
                   "-pix_fmt", "yuv420p", *sync, "-c:a", "copy",
                   "-map_metadata", "0", "-map_chapters", "0", "-movflags", "+faststart", dst]
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
                for _ in range(15):
                    try:
                        os.replace(src_path, dst_path)
                        return True
                    except PermissionError:
                        time.sleep(0.5)
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
            for _ in range(15):
                try:
                    os.replace(src_path, dst_path)
                    return True
                except PermissionError:
                    time.sleep(0.5)
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
        ("helium", local / "imput" / "Helium" / "User Data"),
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
        found = next((c for c in candidates if c["browser"] == "helium"), None)
        if found:
            return "chromium", found["profile"]
        for browser in ("chrome", "edge", "brave"):
            if any(c["browser"] == browser for c in candidates):
                log(f"Cookies: usando {browser} sin verificar sesión de Instagram. "
                    "Si falla, elegí Zen/Firefox en ⚙ SESIÓN IG.")
                return browser, None
        return None, None
    if choice == "helium":
        found = next((c for c in browser_profile_candidates() if c["browser"] == "helium"), None)
        if not found:
            raise RuntimeError("No encontré el perfil de Helium. Abrí Helium, iniciá sesión en Instagram y volvé a intentar.")
        return "chromium", found["profile"]
    if choice in ("chrome", "edge", "brave", "chromium", "opera", "vivaldi"):
        return choice, None
    if choice.startswith("firefox:"):
        profile = choice.split(":", 1)[1].strip().strip('"')
        if profile and Path(profile).exists():
            return "firefox", profile
        raise RuntimeError("La ruta del perfil Firefox/Zen configurado ya no existe. Elegí Auto o seleccioná el navegador otra vez.")
    raise RuntimeError("Navegador de cookies no reconocido. Elegí Auto, Zen, Firefox, Helium, Chrome, Edge o Brave en ⚙ SESIÓN.")

COOKIES_FILE = APP_DIR / "instagram_cookies.txt"
YT_COOKIES = APP_DIR / "youtube_cookies.txt"

def yt_cookie_opts(url):
    u = str(url).lower()
    if ("youtube.com" in u or "youtu.be" in u) and YT_COOKIES.is_file() and YT_COOKIES.stat().st_size > 0:
        return {"cookiefile": str(YT_COOKIES)}
    return {}

def cookies_file_path(cfg=None):
    try:
        if COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 0:
            return str(COOKIES_FILE)
    except OSError:
        pass
    return None

class _QuietLog:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass

BROWSER_PROC_HINT = {"helium": "helium", "chrome": "chrome", "edge": "msedge", "brave": "brave",
                     "zen": "zen", "firefox": "firefox"}
BROWSER_PRETTY = {"helium": "Helium", "chrome": "Chrome", "edge": "Edge", "brave": "Brave",
                  "zen": "Zen", "firefox": "Firefox"}

def _low_integrity():
    """True si este proceso corre con integridad BAJA (no puede escribir fuera de IndieDL).

    Lee el nivel del token (RID < 0x2000), asi que no depende del idioma de Windows.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
        tok = wintypes.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):
            return False
        try:
            need = wintypes.DWORD(0)
            adv.GetTokenInformation(tok, 25, None, 0, ctypes.byref(need))  # TokenIntegrityLevel
            buf = ctypes.create_string_buffer(need.value)
            if not adv.GetTokenInformation(tok, 25, buf, need, ctypes.byref(need)):
                return False
            sid = ctypes.c_void_p.from_buffer(buf).value
            count = adv.GetSidSubAuthorityCount(sid).contents.value
            rid = adv.GetSidSubAuthority(sid, count - 1).contents.value
            return rid < 0x2000
        finally:
            k32.CloseHandle(tok)
    except Exception:
        return False

def _is_lock_error(exc):
    low = str(exc).lower()
    return "permission" in low or "errno 13" in low or "could not copy" in low or "being used" in low

def running_browser_processes(key):
    if os.name != "nt":
        return []
    hint = BROWSER_PROC_HINT.get(key, key)
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20, creationflags=NO_WINDOW).stdout
    except Exception:
        return []
    names = set()
    for line in out.splitlines():
        m = re.match(r'"([^"]+)"', line.strip())
        if m and hint in m.group(1).lower() and m.group(1).lower().endswith(".exe"):
            names.add(m.group(1))
    return sorted(names)

def close_browser_processes(names):
    for n in names:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/IM", n], capture_output=True, timeout=20,
                           creationflags=NO_WINDOW)
        except Exception:
            pass

def _instagram_cookie_rows(jar):
    import time as _t
    far = int(_t.time()) + 365 * 24 * 3600
    rows, has = ["# Netscape HTTP Cookie File"], False
    for c in jar:
        dom = c.domain or ""
        if "instagram.com" not in dom:
            continue
        if c.name == "sessionid" and c.value:
            has = True
        exp = int(c.expires) if c.expires and int(c.expires) > _t.time() else far
        rows.append("\t".join([dom, "TRUE" if dom.startswith(".") else "FALSE", c.path or "/",
                               "TRUE" if c.secure else "FALSE", str(exp), c.name, c.value or ""]))
    return rows, has

def import_instagram_cookies_auto(cfg=None):
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
    except Exception as exc:
        return False, "error", f"yt-dlp no disponible: {exc}"
    choice = str((cfg or {}).get("cookies_browser", "auto") or "auto").lower()
    order, seen = [], set()
    for c in sorted(browser_profile_candidates(), key=lambda c: (c["browser"] != choice,)):
        name = "firefox" if c["browser"] in ("zen", "firefox") else ("chromium" if c["browser"] == "helium" else c["browser"])
        key = (name, c["profile"])
        if key not in seen:
            seen.add(key)
            order.append((name, c["profile"], c["browser"]))
    if not order:
        return False, "error", "No encontré ningún navegador con perfil en esta PC."
    locked, nosession, errors = None, False, []
    for name, profile, label in order:
        try:
            jar = extract_cookies_from_browser(name, profile, _QuietLog())
        except Exception as exc:
            if _is_lock_error(exc):
                locked = locked or label
            errors.append(f"{label}: {str(exc)[:150]}")
            continue
        rows, has = _instagram_cookie_rows(jar)
        if has:
            try:
                APP_DIR.mkdir(parents=True, exist_ok=True)
                COOKIES_FILE.write_text("\n".join(rows) + "\n", encoding="utf-8")
            except OSError as exc:
                return False, "error", f"No pude guardar las cookies: {exc}"
            log(f"Sesión de Instagram detectada en {label} ({len(rows) - 1} cookies guardadas).")
            return True, "ok", label
        nosession = True
    if locked:
        return False, "locked", locked
    if nosession:
        return False, "nosession", ""
    return False, "error", " | ".join(errors)[:400]

def auto_fail_text(status, info):
    if status == "nosession":
        return "Encontré navegadores pero ninguno tiene sesión de Instagram. Iniciá sesión en uno e intentá de nuevo."
    if status == "locked":
        return f"{BROWSER_PRETTY.get(info, info)} está abierto y bloquea sus cookies."
    return "No pude leer la sesión automáticamente. Usá COOKIES.TXT. " + (info or "")

def gallery_dl_args(cfg, use_cookies=True):
    args = gallery_dl_command()
    if not use_cookies:
        log("Cookies para gallery-dl: ninguna (acceso anónimo)")
        return args
    cf = cookies_file_path(cfg)
    if cf:
        args.extend(["--cookies", cf])
        log("Cookies para gallery-dl: archivo cookies.txt")
        return args
    browser, profile = cookie_source(cfg)
    if browser:
        selector = f"{browser}:{profile}" if profile else browser
        args.extend(["--cookies-from-browser", selector])
        log(f"Cookies para gallery-dl: navegador={browser}, perfil={'detectado' if profile else 'predeterminado'}")
    else:
        log("Cookies del navegador no configuradas; gallery-dl intentará acceder sin sesión.")
    return args

def add_cookie_lock_hint(detail):
    lowered = str(detail).lower().replace("/", "\\")
    if "permission denied" in lowered and ("cookies" in lowered or "\\cookies" in lowered):
        return (detail + "\nWindows no permitió leer la base de cookies porque Helium la tiene abierta. "
                "Cerrá Helium completamente (incluido el icono junto al reloj) y reintentá. "
                "Si sigue igual (Chromium cifra las cookies y a veces no se pueden leer ni con el navegador cerrado), "
                "abrí ⚙ SESIÓN IG → 'Archivo cookies.txt' y cargá un cookies.txt exportado de instagram.com.")
    return detail

def _parse_gdl_dump(stdout):
    values = []
    text = stdout.strip()
    if text:
        try:
            values.append(json.loads(text))
        except Exception:
            dec, pos = json.JSONDecoder(), 0
            while pos < len(text):
                while pos < len(text) and text[pos].isspace():
                    pos += 1
                if pos >= len(text):
                    break
                try:
                    obj, pos = dec.raw_decode(text, pos)
                    values.append(obj)
                except Exception:
                    nl = text.find("\n", pos)
                    pos = len(text) if nl < 0 else nl + 1
    found = []

    def walk(v):
        if isinstance(v, list):
            if len(v) >= 3 and v[0] == 3 and isinstance(v[1], str) and isinstance(v[2], dict):
                meta = dict(v[2])
                meta["_url"] = v[1]
                found.append(meta)
            else:
                for x in v:
                    walk(x)
        elif isinstance(v, dict):
            direct = v.get("_url") or v.get("url") or v.get("file_url") or v.get("gdl_file_url")
            if isinstance(direct, str) and direct.startswith("http"):
                found.append(dict(v))
    for v in values:
        walk(v)
    entries = []
    for e in found:
        direct = e.get("_url") or e.get("url") or e.get("file_url") or e.get("gdl_file_url")
        if direct:
            e["_indiedl_url"] = direct
            entries.append(e)
    return entries

def _cookie_unreadable(msg):
    low = str(msg).lower()
    return ("permission denied" in low and "cookies" in low) or "could not decrypt" in low or "failed to decrypt" in low

def gallery_dl_extract(url, cfg, timeout=90):
    try:
        return _gallery_dl_extract(url, cfg, timeout, True)
    except RuntimeError as first:
        if not _cookie_unreadable(first) or cookies_file_path(cfg):
            raise
        log("No se pudieron leer las cookies del navegador; reintento sin sesión.")
        try:
            return _gallery_dl_extract(url, cfg, timeout, False)
        except RuntimeError:
            raise first

def _gallery_dl_extract(url, cfg, timeout, use_cookies):
    cmd = gallery_dl_args(cfg, use_cookies) + ["--dump-json", "--simulate", "--no-colors", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=NO_WINDOW)
    except FileNotFoundError as exc:
        raise RuntimeError("No está instalado gallery-dl. Ejecutá el instalador actualizado de IndieDL.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Instagram tardó demasiado en responder. Probá de nuevo o revisá la sesión del navegador.") from exc
    entries = _parse_gdl_dump(proc.stdout or "")
    if not entries:
        detail = (proc.stderr or "").strip()
        if not detail and (proc.stdout or "").lstrip()[:1] not in ("[", "{"):
            detail = (proc.stdout or "").strip()
        if proc.returncode:
            detail = detail[-1000:]
        if not detail:
            detail = "gallery-dl no devolvió elementos de imagen para este enlace."
        detail = add_cookie_lock_hint(detail)
        if "permission denied" not in detail.lower() and any(word in detail.lower() for word in ("login", "cookie", "401", "403", "checkpoint", "challenge", "redirect to login")):
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
    def _run(use_cookies):
        a = gallery_dl_args(cfg, use_cookies) + [
            "--directory", folder,
            "--filename", "{post_id}_{num}.{extension}",
            "--range", rango,
            "--no-colors",
            url,
        ]
        return subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=300, creationflags=NO_WINDOW)
    proc = _run(True)
    if proc.returncode and _cookie_unreadable((proc.stderr or "") + (proc.stdout or "")) and not cookies_file_path(cfg):
        log("Cookies ilegibles al descargar; reintento sin sesión.")
        proc = _run(False)
    if cancel.is_set():
        raise RuntimeError("Cancelado")
    if proc.returncode:
        detail = (proc.stderr or proc.stdout or f"gallery-dl terminó con código {proc.returncode}").strip()
        detail = add_cookie_lock_hint(detail)
        if "permission denied" not in detail.lower() and any(word in detail.lower() for word in ("login", "cookie", "401", "403", "checkpoint", "challenge", "redirect to login")):
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
    try:
        import yt_dlp  # noqa: F401
        return None
    except Exception:
        pass
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
    job_suffix = (f" [clip {fmt_hms(section[0]).replace(':', '-')}-"
                  f"{fmt_hms(section[1]).replace(':', '-')}-{uuid.uuid4().hex[:6]}]"
                  if section else "")
    done_file = TEMP_DIR / f"final_{int(t0)}.txt"
    cmd = [exe, "--newline", "--no-colors", "--no-playlist", "--windows-filenames",
           "--no-mtime",
           "--retries", "10", "--fragment-retries", "10", "--socket-timeout", "30",
           "--concurrent-fragments", "4",
           "-P", f"home:{folder}", "-P", f"temp:{TEMP_DIR}",
           "-o", f"%(title).80s [%(id)s]{job_suffix}.%(ext)s",
           "--progress-template", "download:IDLP|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
                                  "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
           "--print-to-file", "after_move:%(title)s|||%(filepath)s", str(done_file)]
    if ff:
        cmd += ["--ffmpeg-location", ff]
    if mode == "audio":
        cmd += ["-f", "bestaudio/best", "-x", "--audio-format", quality or AUDIO_CODEC]
        if (quality or AUDIO_CODEC) != "wav":
            cmd += ["--audio-quality", AUDIO_QUALITY + "K"]
        if section:
            cmd += ["--download-sections", f"*{section[0]}-{section[1]}"]
    else:
        cmd += ["-f", vfmt(quality), "--merge-output-format", "mp4"]
        if section:
            cmd += ["--download-sections", f"*{section[0]}-{section[1]}", "--force-keyframes-at-cuts"]
    if "instagram.com" in url.lower() and cookies_file_path(cfg):
        cmd += ["--cookies", cookies_file_path(cfg)]
        q.put(("log", "Sesión de Instagram: archivo cookies.txt"))
    elif "instagram.com" in url.lower():
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
        if section:
            raise RuntimeError(
                "yt-dlp no confirmó el archivo recortado. No voy a marcar el video completo como si fuera el fragmento pedido. "
                "Revisá si FFmpeg está disponible y vuelve a intentarlo."
            )
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
        if section:
            q.put(("log", f"Rango In/Out solicitado: {fmt_hms(section[0])} → {fmt_hms(section[1])}"))
        if mode == "image":
            gallery_dl_download(url, folder, cfg, q, cancel, image_indices)
            return

        ff = ffmpeg_path()
        if mode in ("video", "audio") and not ff:
            raise RuntimeError(
                "Falta ffmpeg. Instalá ffmpeg (winget install Gyan.FFmpeg) "
                "o reinstalá IndieDL. Sin ffmpeg no se puede unir audio y video."
            )

        try:
            maybe_update_ytdlp(cfg, q)
        except Exception:
            pass

        exe = ytdlp_exe() if mode in ("video", "audio") else None
        if exe:
            final, _title = exe_download(exe, url, mode, TEMP_DIR, cfg, q, quality, cancel, section)
            st = {"files": [], "meta": True, "title": _title}
            res = {"title": _title}
        else:
            try:
                import yt_dlp
            except Exception as exc:
                raise RuntimeError(
                    "No encontré yt-dlp: falta el ejecutable y también el módulo "
                    "de Python. Ejecutá INSTALAR.bat y volvé a intentar."
                ) from exc
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
            job_suffix = (f" [clip {fmt_hms(section[0]).replace(':', '-')}-"
                          f"{fmt_hms(section[1]).replace(':', '-')}-{uuid.uuid4().hex[:6]}]"
                          if section else "")
            
            opts = {
                "outtmpl": image_prefix + f"%(title).80s [%(id)s]{job_suffix}.%(ext)s",
                "noplaylist": mode != "image", "quiet": True, "no_warnings": True, "noprogress": True,
                "windowsfilenames": True, "progress_hooks": [hook], "postprocessor_hooks": [phook],
                "concurrent_fragment_downloads": 4,
                "paths": {"home": str(TEMP_DIR), "temp": str(TEMP_DIR)}, 
            }
            if ff:
                opts["ffmpeg_location"] = ff
            opts.update(yt_cookie_opts(url))
            if mode == "video":
                opts.update(format=vfmt(quality), merge_output_format="mp4")
                if section:
                    opts["download_sections"] = [f"*{section[0]}-{section[1]}"]
                    opts["force_keyframes_at_cuts"] = True
            elif mode == "audio":
                opts.update(format="bestaudio/best", postprocessors=[{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": quality or AUDIO_CODEC, "preferredquality": AUDIO_QUALITY}])
                if section:
                    opts["download_sections"] = [f"*{section[0]}-{section[1]}"]
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

        if section:
            if not final or not os.path.isfile(final):
                raise RuntimeError("No se generó ningún archivo para el rango In/Out seleccionado.")
            final = enforce_clip(ff, final, section, mode, quality, q)

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

        # === MOVER EL ARCHIVO A LA CARPETA DE DESTINO ===
        q.put(("log", "Moviendo archivo a la carpeta de destino..."))
        target_dir = Path(folder)
        target_dir.mkdir(parents=True, exist_ok=True)
        final_path = Path(final)
        target_path = target_dir / final_path.name
        
        if target_path.exists():
            n = 1
            while True:
                target_path = target_dir / f"{final_path.stem} ({n}){final_path.suffix}"
                if not target_path.exists():
                    break
                n += 1
                
        folder_guardado = folder
        move_exitoso = False
        try:
            # Intentar COPIAR en lugar de MOVER suele evadir bloqueos de antivirus
            for intento in range(10):
                try:
                    shutil.copy2(str(final_path), str(target_path))
                    move_exitoso = True
                    break
                except (PermissionError, OSError) as e:
                    if intento == 9:
                        raise e
                    time.sleep(0.5)
            
            if move_exitoso:
                final = str(target_path)
                try: os.remove(final_path)
                except Exception: pass
                q.put(("log", "Guardado exitoso en: " + final))
        except Exception as move_err:
            q.put(("log", f"Error al mover a la carpeta de destino: {move_err}"))
            if _low_integrity():
                msg = (f"No se pudo guardar en {folder}: IndieDL corre con integridad baja "
                       f"(etiqueta heredada de la carpeta IndieDL).\n"
                       f"Solución: ejecuta INSTALAR.bat otra vez, o en PowerShell:\n"
                       f'icacls "%LOCALAPPDATA%\\IndieDL" /setintegritylevel "(OI)(CI)M" /T\n'
                       f"El archivo se guardó en la carpeta temporal: {TEMP_DIR}")
            else:
                msg = (f"No se pudo guardar en {folder} por un bloqueo de Windows.\n"
                       f"(Puede ser la 'Protección contra ransomware' de Windows Defender, "
                       f"otro antivirus, o que el archivo esté abierto en otro programa. "
                       f"El archivo se guardó en la carpeta temporal: {TEMP_DIR})")
            q.put(("note", msg))
            q.put(("warn", msg))
            folder_guardado = str(TEMP_DIR)
            final = str(final_path)

        if mode == "video" and ff and "Audio:" not in probe(ff, final):
            q.put(("log", "ATENCION: el archivo final NO trae pista de audio"))
        q.put(("stage", 3, "Finalizando"))
        q.put(("log", "Archivo final verificado: " + os.path.basename(final)))
        q.put(("done", folder_guardado, st["title"] or (res or {}).get("title") or url))
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

def cached_header(w=1040, h=120):
    try:
        from PIL import Image
    except Exception:
        return halftone_header(w, h)
    cache_dir = APP_DIR / "cache"
    path = cache_dir / f"header_{w}x{h}_v2.png"
    try:
        if path.is_file() and path.stat().st_size > 512:
            img = Image.open(path)
            img.load()
            return img.convert("RGB")
    except Exception as exc:
        log(f"cached_header lectura: {exc!r}")
    img = halftone_header(w, h)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        img.save(path)
    except Exception as exc:
        log(f"cached_header guardado: {exc!r}")
    return img

def build_app():
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox
    ctk.set_appearance_mode("dark")
    BLACK, WHITE, YEL, YEL_H = "#0A0D10", "#F4F6F8", "#FFF333", "#FFE600"
    GRAY, RED, GREEN = "#AAB4BE", "#FF5B65", "#4ADE80"
    HEAVY = "Segoe UI Black"
    VIDEO_Q = ["Mejor", "1080p", "720p"]
    AUDIO_F = ["wav", "mp3", "m4a"]
    IMAGE_F = ["Original"]
    QFONT = "Segoe UI"
    SPIN = "◐◓◑◒"

    class SmoothScroll(ctk.CTkFrame):
        def __init__(self, master, fg_color=BLACK, registry=None,
                     scrollbar_button_color="#2B333C", **kwargs):
            super().__init__(master, fg_color=fg_color, corner_radius=0, **kwargs)
            self._bg = fg_color
            self._registry = registry
            if registry is not None:
                registry.append(self)
            self._content_h = 0
            self._anim_job = None
            self._anim_start = 0.0
            self._anim_target = 0.0
            self._anim_t0 = 0.0
            self._anim_dur = 0.18
            self._visible_frac = 1.0

            self.grid_rowconfigure(0, weight=1)
            self.grid_columnconfigure(0, weight=1)

            self._view = tk.Canvas(self, bg=fg_color, highlightthickness=0,
                                   bd=0, relief="flat", takefocus=0)
            self._view.grid(row=0, column=0, sticky="nsew")
            self._scrollbar = ctk.CTkScrollbar(
                self, orientation="vertical", width=10,
                fg_color=fg_color, button_color=scrollbar_button_color,
                button_hover_color="#4A5763", command=self._on_scrollbar)
            self._scrollbar.grid(row=0, column=1, sticky="ns", padx=(2, 0))
            self.body = ctk.CTkFrame(self._view, fg_color=fg_color, corner_radius=0)
            self._window = self._view.create_window((0, 0), window=self.body, anchor="nw")
            self._view.configure(yscrollcommand=self._on_yview)
            self._animating = False

            self.body.bind("<Configure>", self._on_body_configure, add="+")
            self._view.bind("<Configure>", self._on_view_configure, add="+")
            self.bind("<Destroy>", self._on_destroy, add="+")

        def _on_body_configure(self, _event=None):
            self._content_h = max(1, self.body.winfo_reqheight())
            self._view.configure(scrollregion=(0, 0, max(1, self.body.winfo_width()), self._content_h))
            self._sync_scrollbar()

        def _on_view_configure(self, event):
            self._view.itemconfigure(self._window, width=max(1, event.width))
            self._sync_scrollbar()

        def _sync_scrollbar(self):
            try:
                need = self._content_h > self._view.winfo_height() + 2
                if need and not self._scrollbar.winfo_ismapped():
                    self._scrollbar.grid()
                elif not need and self._scrollbar.winfo_ismapped():
                    self._scrollbar.grid_remove()
            except Exception:
                pass

        def _on_yview(self, first, last):
            try:
                self._scrollbar.set(first, last)
            except Exception:
                pass
            self._visible_frac = max(0.0, float(last) - float(first))
            if self._animating or self._anim_job is not None:
                return
            self._anim_target = float(first)
            self._anim_start = float(first)

        def _on_scrollbar(self, *args):
            self._cancel_anim()
            self._view.yview(*args)
            pos = self._view.yview()[0]
            self._anim_target = float(pos)
            self._anim_start = float(pos)

        def _cancel_anim(self):
            if self._anim_job is not None:
                try:
                    self.after_cancel(self._anim_job)
                except Exception:
                    pass
                self._anim_job = None
            self._animating = False

        def at_bottom(self, tolerance=0.02):
            try:
                return self._view.yview()[1] >= 1.0 - tolerance
            except Exception:
                return True

        def scroll_pixels(self, px):
            if not self.winfo_ismapped():
                return
            height = self._view.winfo_height()
            if self._content_h <= height + 2:
                return
            now = time.perf_counter()
            current = float(self._view.yview()[0])
            if self._anim_job is None or now > self._anim_t0 + self._anim_dur + 0.05:
                self._anim_target = current
            frac = float(px) / max(1.0, float(self._content_h))
            self._anim_target = max(0.0, min(1.0, self._anim_target + frac))
            self._anim_start = current
            self._anim_t0 = now
            self._anim_dur = 0.12 if abs(px) < 40 else 0.19
            if self._anim_job is None:
                self._anim_job = self.after(8, self._anim_tick)

        def scroll_to_top(self, animate=False):
            self._cancel_anim()
            try:
                self._view.yview_moveto(0.0)
                self._anim_target = 0.0
                self._anim_start = 0.0
            except Exception:
                pass

        def scroll_to_end(self):
            if not self.winfo_ismapped():
                return
            now = time.perf_counter()
            current = float(self._view.yview()[0])
            self._cancel_anim()
            self._anim_start = current
            self._anim_target = 1.0
            self._anim_t0 = now
            self._anim_dur = 0.22
            self._anim_job = self.after(8, self._anim_tick)

        def _anim_tick(self):
            self._anim_job = None
            try:
                elapsed = time.perf_counter() - self._anim_t0
                p = 1.0 if self._anim_dur <= 0 else min(1.0, elapsed / self._anim_dur)
                eased = 1.0 - (1.0 - p) ** 3
                pos = self._anim_start + (self._anim_target - self._anim_start) * eased
                self._animating = True
                try:
                    self._view.yview_moveto(max(0.0, min(1.0, pos)))
                finally:
                    self._animating = False
                if p < 1.0:
                    self._anim_job = self.after(8, self._anim_tick)
                else:
                    real = float(self._view.yview()[0])
                    self._anim_target = real
                    self._anim_start = real
            except Exception:
                self._animating = False
                self._anim_job = None

        def _on_destroy(self, event):
            if event.widget is not self:
                return
            self._cancel_anim()
            if self._registry is not None:
                try:
                    self._registry.remove(self)
                except ValueError:
                    pass

    class App(ctk.CTk):
        def __init__(self, mode, url, batch=None, clip=None):
            self._boot_t0 = time.perf_counter()
            super().__init__()
            self._mark("super")
            self.withdraw()
            self._alpha_ok = True
            try:
                self.attributes("-alpha", 0.0)
            except Exception:
                self._alpha_ok = False
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
            self._metadata_generation = 0
            self._last_clip_url = None
            self._last_site = None
            self._logo_cache = {}
            self._scroll_areas = []
            self._bar_disp = {}
            self._bar_target = {}
            self._bar_jobs = {}
            self._gallery_dl_ok = bool(self.cfg.get("gallery_dl_ok", True))
            self._last_warn = ""
            self.stage = -1
            self.spin_i = 0
            self.t0 = time.time()
            self.title("Indie Now DL")
            screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
            width = min(1480, max(760, screen_w - 48))
            height = min(860, max(560, screen_h - 96))
            min_w = min(1180, max(760, screen_w - 48))
            min_h = min(680, max(560, screen_h - 96))
            self.minsize(min_w, min_h)
            self.resizable(True, True)
            self.geometry(f"{width}x{height}+{max(0, (screen_w-width)//2)}+{max(0, (screen_h-height)//2)}")
            self.configure(fg_color="#0D1116")
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=0)
            self.grid_rowconfigure(0, weight=1)
            self._mark("geometry")

            left = ctk.CTkFrame(self, fg_color="#0D1116", corner_radius=0)
            left.grid(row=0, column=0, sticky="nsew")
            right = ctk.CTkFrame(self, fg_color=BLACK, corner_radius=0, width=340)
            right.grid(row=0, column=1, sticky="nsew")
            right.grid_propagate(False)

            self.hdr = ctk.CTkImage(cached_header(1040, 120), size=(1040, 120))
            hf = ctk.CTkFrame(left, fg_color="#0D1116", corner_radius=0, height=120)
            hf.pack(fill="x")
            hf.pack_propagate(False)
            ctk.CTkLabel(hf, text="", image=self.hdr).place(relx=0.5, rely=0.5, anchor="center")
            band = ctk.CTkFrame(left, fg_color=BLACK, corner_radius=0, height=42)
            band.pack(fill="x")
            band.pack_propagate(False)
            ctk.CTkLabel(band, text=spaced("DESCARGA VIDEOS, AUDIOS E IMÁGENES"), text_color=YEL,
                         font=(HEAVY, 15)).pack(expand=True)
            self.status_pill = ctk.CTkLabel(
                band, text="●  LISTO", text_color=GREEN, fg_color="#11181E",
                corner_radius=10, font=(HEAVY, 10), height=24, width=94)
            self.status_pill.place(relx=1.0, rely=0.5, x=-12, anchor="e")
            ctk.CTkFrame(left, fg_color=YEL, corner_radius=0, height=5).pack(fill="x")
            self._mark("header")

            body = ctk.CTkFrame(left, fg_color="#0D1116", corner_radius=0)
            body.pack(fill="both", expand=True, padx=22, pady=(16, 14))
            self.form = ctk.CTkFrame(body, fg_color="#0D1116", corner_radius=0)
            self.form.pack(fill="both", expand=True)
            self.form.grid_columnconfigure((0, 1), weight=1, uniform="form")
            self.form.grid_rowconfigure(0, weight=1)
            self.pv = ctk.CTkFrame(body, fg_color="#0D1116", corner_radius=0)
            self.build_form(url)
            self._mark("form")
            self.build_progress()
            self._mark("progress")

            hd = ctk.CTkFrame(right, fg_color="transparent")
            hd.pack(fill="x", padx=16, pady=(18, 8))
            self.r_title = ctk.CTkLabel(hd, text="▤  Historial", font=(HEAVY, 17), text_color=YEL)
            self.r_title.pack(side="left")
            self.r_count = ctk.CTkLabel(hd, text="", font=(HEAVY, 10), text_color="#0D1116",
                                        fg_color="#2A333D", corner_radius=8, height=20, width=26)
            self.r_count.pack(side="left", padx=(8, 0))
            self.b_hist = ctk.CTkButton(hd, text="▤ HIST.", width=68, height=26, corner_radius=3,
                                        font=(HEAVY, 10), command=lambda: self.show_panel("hist"))
            self.b_live = ctk.CTkButton(hd, text="● EN VIVO", width=84, height=26, corner_radius=3,
                                        font=(HEAVY, 10), command=lambda: self.show_panel("live"))
            self.b_live.pack(side="right")
            self.b_hist.pack(side="right", padx=(0, 6))
            self.rbar = ctk.CTkProgressBar(right, height=4, corner_radius=2, fg_color="#1B2229",
                                           progress_color=YEL)
            self.rbar.set(0)
            self.rbar.pack(fill="x", padx=16)
            self.hist = SmoothScroll(right, fg_color=BLACK, registry=self._scroll_areas,
                                     scrollbar_button_color="#2B333C")
            self.live = SmoothScroll(right, fg_color=BLACK, registry=self._scroll_areas,
                                     scrollbar_button_color="#2B333C")
            self._mark("scrolls")
            self.panel = None
            self.render_hist()
            self._mark("hist")
            self.show_panel("hist")

            self.set_mode(self.cur_mode)
            self._mark("setmode")
            if not self._gallery_dl_ok:
                self._apply_gallery_state(False, persist=False, notify=False)
            if batch:
                self.enter_batch(batch)
            if clip:
                self.after(500, lambda c=clip: self.apply_clip(c))
            self.bind("<Return>", lambda e: self.start() if self.form.winfo_ismapped() else None)
            self.bind_all("<MouseWheel>", self._on_wheel_all, add="+")
            if sys.platform.startswith("linux"):
                self.bind_all("<Button-4>", self._on_wheel_all, add="+")
                self.bind_all("<Button-5>", self._on_wheel_all, add="+")
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(100, self.poll)
            self.after(120, self.tick)
            self.after(0, self._reveal)
            self.after(400, self._schedule_gallery_check)

        def _mark(self, tag):
            if os.environ.get("INDIEDL_PROFILE"):
                log(f"boot {tag} {int((time.perf_counter() - self._boot_t0) * 1000)} ms")

        def _check_gallery_dl(self):
            try:
                proc = subprocess.run(gallery_dl_command() + ["--version"],
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

        def _reveal(self):
            try:
                self.update_idletasks()
            except Exception:
                pass
            self._mark("idle")
            try:
                self.deiconify()
                self._mark("deiconify")
                self._apply_dark_titlebar()
                self.lift()
            except Exception:
                pass
            self._mark("lift")
            if self._alpha_ok:
                self._fade_in(0)
            else:
                self._finish_reveal()

        def _fade_in(self, step):
            steps = 4
            p = min(1.0, float(step) / steps)
            alpha = 1.0 - (1.0 - p) ** 3
            try:
                self.attributes("-alpha", alpha)
            except Exception:
                self._alpha_ok = False
            if step < steps:
                self.after(12, lambda: self._fade_in(step + 1))
            else:
                self._finish_reveal()

        def _finish_reveal(self):
            if getattr(self, "_revealed", False):
                return
            self._revealed = True
            try:
                self.attributes("-alpha", 1.0)
            except Exception:
                pass
            try:
                self.focus_force()
            except Exception:
                pass
            self.after(1, self._grow_hist)
            log(f"UI lista en {int((time.perf_counter() - self._boot_t0) * 1000)} ms")

        def _apply_dark_titlebar(self):
            if os.name != "nt":
                return
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
                value = ctypes.c_int(1)
                for attr in (20, 19):
                    if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                            hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                        break
            except Exception:
                pass

        def _on_close(self):
            try:
                if getattr(self, "_hist_grow_job", None):
                    self.after_cancel(self._hist_grow_job)
            except Exception:
                pass
            self._hist_pending = None
            for job in list(self._bar_jobs.values()):
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
            self._bar_jobs.clear()
            try:
                self.destroy()
            except Exception:
                pass

        def _wheel_target(self, x_root, y_root):
            for area in reversed(self._scroll_areas):
                try:
                    if not area.winfo_ismapped():
                        continue
                    x, y = area.winfo_rootx(), area.winfo_rooty()
                    if x <= x_root < x + area.winfo_width() and \
                            y <= y_root < y + area.winfo_height():
                        return area
                except Exception:
                    continue
            return None

        def _on_wheel_all(self, event):
            try:
                target = self._wheel_target(event.x_root, event.y_root)
                if target is None:
                    return None
                try:
                    widget = self.winfo_containing(event.x_root, event.y_root)
                    if widget is not None and widget.winfo_class() in ("Text", "Listbox", "TCombobox"):
                        return None
                except Exception:
                    pass
                if getattr(event, "num", None) in (4, 5):
                    px = -44.0 if event.num == 4 else 44.0
                else:
                    delta = float(getattr(event, "delta", 0) or 0)
                    if delta == 0:
                        return None
                    px = -delta * 0.48
                target.scroll_pixels(px)
                return "break"
            except Exception:
                return None

        def _schedule_gallery_check(self):
            checked = float(self.cfg.get("gallery_dl_checked") or 0)
            has_cache = "gallery_dl_ok" in self.cfg
            if has_cache:
                self._apply_gallery_state(bool(self.cfg.get("gallery_dl_ok")),
                                          persist=False, notify=False)
                if time.time() - checked < 6 * 3600:
                    return

            def worker():
                ok = self._check_gallery_dl()
                self.after(0, lambda: self._apply_gallery_state(ok, persist=True, notify=True))

            threading.Thread(target=worker, daemon=True).start()

        def _apply_gallery_state(self, ok, persist=True, notify=True):
            changed = bool(ok) != bool(self._gallery_dl_ok)
            self._gallery_dl_ok = bool(ok)
            try:
                if ok:
                    self.b_image.configure(state="normal", text="▧  IMAGEN")
                else:
                    self.b_image.configure(state="disabled", text="▧  IMAGEN (sin gallery-dl)")
                    if self.cur_mode == "image":
                        self.set_mode("video")
            except Exception:
                pass
            if persist:
                try:
                    self.cfg["gallery_dl_ok"] = bool(ok)
                    self.cfg["gallery_dl_checked"] = time.time()
                    save_cfg(self.cfg)
                except Exception:
                    pass
            if notify and changed:
                log("gallery-dl disponible" if ok else "gallery-dl no disponible")

        def _set_status(self, text, color):
            try:
                self.status_pill.configure(text=text, text_color=color)
            except Exception:
                pass

        def _set_bar_smooth(self, bar, target):
            try:
                target = max(0.0, min(1.0, float(target)))
            except Exception:
                return
            self._bar_target[bar] = target
            if bar in self._bar_jobs:
                return

            def tick():
                try:
                    current = self._bar_disp.get(bar, 0.0)
                    goal = self._bar_target.get(bar, target)
                    nxt = current + (goal - current) * 0.32
                    if abs(goal - nxt) < 0.004:
                        nxt = goal
                    self._bar_disp[bar] = nxt
                    bar.set(nxt)
                    if nxt != goal:
                        self._bar_jobs[bar] = self.after(16, tick)
                    else:
                        self._bar_jobs.pop(bar, None)
                except Exception:
                    self._bar_jobs.pop(bar, None)

            self._bar_jobs[bar] = self.after(16, tick)

        def _set_rbar(self, value):
            self._set_bar_smooth(self.rbar, value)

        def _reset_bars(self):
            for job in list(self._bar_jobs.values()):
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
            self._bar_jobs.clear()
            self._bar_disp.clear()
            self._bar_target.clear()
            for row in getattr(self, "rows", []):
                try:
                    row["bar"].stop()
                    row["bar"].set(0)
                    row["bar"].place_forget()
                except Exception:
                    pass
            try:
                self.rbar.set(0)
            except Exception:
                pass

        def build_form(self, url):
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
                                checkbox_height=20).pack(anchor="w", pady=2)

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
                il = ctk.CTkLabel(ic, text="", font=(HEAVY, 14), text_color=WHITE, fg_color="transparent")
                il.pack(expand=True)
                tx = ctk.CTkLabel(r, text=name, font=("Segoe UI Semibold", 15), text_color="#999", anchor="w")
                tx.grid(row=0, column=1, sticky="w", pady=(4, 0))
                pc = ctk.CTkLabel(r, text="", font=(HEAVY, 13), text_color=WHITE)
                pc.grid(row=0, column=2, sticky="e")
                track = ctk.CTkFrame(r, fg_color="transparent", height=10)
                track.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(4, 0))
                track.grid_propagate(False)
                bar = ctk.CTkProgressBar(track, height=7, corner_radius=3, fg_color="#1E262E",
                                         progress_color=YEL, border_width=0, mode="determinate")
                bar.place(relx=0, rely=0.5, relwidth=1, anchor="w")
                bar.set(0)
                bar.place_forget()
                ln = ctk.CTkFrame(r, width=2, height=18, fg_color="#CCC", corner_radius=0)
                if i < len(STAGES) - 1:
                    ln.grid(row=2, column=0, pady=(2, 0))
                self.rows.append(dict(ic=ic, il=il, tx=tx, pc=pc, bar=bar, track=track, name=name))

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
                                        font=(HEAVY, 15), command=lambda: self.open_dir(self.cfg.get("last_saved", self.cfg["last_dir"])))
            self.b_back = ctk.CTkButton(bt, text="DESCARGAR OTRO", height=48, corner_radius=4, fg_color=YEL,
                                        hover_color=YEL_H, text_color=BLACK, border_width=3, border_color=BLACK,
                                        font=(HEAVY, 15), command=self.back)

        def show_buttons(self, mode):
            for b in (self.b_cancel, self.b_open, self.b_back):
                b.grid_remove()
            order = (self.b_cancel, self.b_open) if mode == "run" else (self.b_open, self.b_back)
            for i, b in enumerate(order):
                b.grid(row=0, column=i, sticky="ew", padx=(0, 6) if i == 0 else (6, 0))

        def _show_row_bar(self, row, mode="indeterminate", reset=False):
            bar = row["bar"]
            try:
                bar.stop()
                bar.configure(mode=mode)
                if mode == "determinate":
                    bar.set(0 if reset else self._bar_disp.get(bar, 0.0))
                if not bar.winfo_ismapped():
                    bar.place(relx=0, rely=0.5, relwidth=1, anchor="w")
                if mode == "indeterminate":
                    bar.start()
            except Exception:
                pass

        def _hide_row_bar(self, row):
            try:
                row["bar"].stop()
                row["bar"].place_forget()
            except Exception:
                pass

        def set_stage(self, idx, text=None):
            self.stage = idx
            for i, r in enumerate(self.rows):
                if i < idx:
                    self._hide_row_bar(r)
                    r["ic"].configure(fg_color=YEL, border_width=0)
                    r["il"].configure(text="✓", text_color=BLACK, font=(HEAVY, 14))
                    r["tx"].configure(text=r["name"], text_color=WHITE, font=("Segoe UI Semibold", 15))
                    r["pc"].configure(text="")
                elif i == idx:
                    r["ic"].configure(fg_color="#0D1116", border_width=2, border_color=YEL)
                    r["il"].configure(text=SPIN[0], text_color=YEL, font=(HEAVY, 15))
                    r["tx"].configure(text=text or r["name"], text_color=WHITE, font=(HEAVY, 15))
                    r["pc"].configure(text="")
                    self._show_row_bar(r, "determinate" if i == 1 else "indeterminate", reset=True)
                else:
                    self._hide_row_bar(r)
                    r["ic"].configure(fg_color="#DDD", border_width=0)
                    r["il"].configure(text="", font=(HEAVY, 14))
                    r["tx"].configure(text=r["name"], text_color="#999", font=("Segoe UI Semibold", 15))
                    r["pc"].configure(text="")
            if 0 <= idx < len(STAGES):
                self.p_top.configure(text=f"{self._prefix}PASO {idx + 1} DE {len(STAGES)}")
                self.p_title.configure(text=text or STAGES[idx])
            if idx >= 1:
                self._set_rbar((idx + 0.35) / max(1, len(STAGES)))

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
            cached = self._logo_cache.get(site)
            if cached is not None:
                return cached
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
            image = ctk.CTkImage(light_image=im, dark_image=im, size=(56, 56))
            self._logo_cache[site] = image
            return image

        def on_url(self):
            url = self.url.get().strip()
            site = site_name(url) if url else "LINK"
            icons = {"YOUTUBE": ("▶", "YouTube"), "INSTAGRAM": ("◎", "Instagram"), "TIKTOK": ("♪", "TikTok"), "X": ("𝕏", "X / Twitter"), "PINTEREST": ("ℙ", "Pinterest"), "LINK": ("↗", "Plataforma")}
            ico, label = icons.get(site, ("↗", "Plataforma"))
            if site != self._last_site:
                self._last_site = site
                self.chip.configure(text=f"{ico}  {label}")
                if hasattr(self, "platform_icon"):
                    self.platform_icon.configure(image=self.make_platform_logo(site), text="")
            valid = bool(url and clean_url(url))
            if hasattr(self, "platform_icon"):
                if not url:
                    self.preview_title.configure(text="Esperando un enlace")
                    self.preview_meta.configure(text="Pegá un enlace para detectar plataforma y detalles")
                    self.thumbnail_label.configure(image=None, text="Sin enlace")
                elif valid:
                    self.preview_title.configure(text="Contenido listo para descargar")
                    self.preview_meta.configure(text=f"{label} · enlace recibido")
                    self.thumbnail_label.configure(image=None, text="")
                else:
                    self.preview_title.configure(text="Enlace no compatible")
                    self.preview_meta.configure(text="Usá un enlace de YouTube, Instagram, TikTok, X o Pinterest")
                    self.thumbnail_label.configure(image=None, text="")
                self.thumbnail_image = None
                if self._meta_job:
                    try: self.after_cancel(self._meta_job)
                    except Exception: pass
                if valid:
                    delay = 0 if url in self._metadata_cache else 350
                    self._meta_job = self.after(delay, lambda u=url: self.fetch_metadata(u))
            if self._last_clip_url != url:
                self._last_clip_url = url
                if hasattr(self, "v_clip") and self.v_clip.get():
                    self.v_clip.set(False)
                    try:
                        self.clip_start.delete(0, "end")
                        self.clip_end.delete(0, "end")
                    except Exception:
                        pass
            self._sync_clip_controls()

        def _sync_clip_controls(self):
            if not (hasattr(self, "clip_toggle") and hasattr(self, "clip_frame")):
                return
            url = self.url.get().strip()
            site = site_name(url) if url else "LINK"
            supported = (site == "YOUTUBE" and self.cur_mode in ("video", "audio")
                         and "/shorts/" not in url.lower() and "/live/" not in url.lower())
            if supported:
                self.clip_toggle.grid()
                self.clip_frame.grid()
            else:
                self.clip_toggle.grid_remove()
                self.clip_frame.grid_remove()
                self.v_clip.set(False)

        def fetch_metadata(self, url):
            if url in self._metadata_cache:
                info = self._metadata_cache[url]
                title = str(info.get("title") or "Contenido detectado")
                author = str(info.get("uploader") or info.get("channel") or info.get("creator") or "Autor no disponible")
                duration = info.get("duration")
                duration_text = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else "Duración no disponible"
                width, height = info.get("width"), info.get("height")
                resolution = f"{width} × {height}" if width and height else "Resolución disponible al descargar"
                meta = f"@{author.lstrip('@')}  ·  {duration_text}  ·  {resolution}  ·  {str(info.get('ext') or 'media').upper()}"
                self.apply_metadata(url, title, meta, None, "Miniatura no disponible")
                return
            if url in self._metadata_loading:
                return
            self._metadata_loading.add(url)
            def worker():
                try:
                    import yt_dlp
                    ensure_temp_dir()
                    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
                            "socket_timeout": 10, "retries": 0, "extractor_retries": 0,
                            "paths": {"temp": str(TEMP_DIR)}}
                    opts.update(yt_cookie_opts(url))
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
                        for item in reversed(thumb_list):
                            if isinstance(item, dict):
                                candidate = item.get("url")
                                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                                    thumb_candidates.append(candidate)
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
            def guarded_worker():
                try:
                    worker()
                finally:
                    self._metadata_loading.discard(url)
            threading.Thread(target=guarded_worker, daemon=True).start()

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
            win.geometry("560x340")
            win.resizable(False, False)
            win.transient(self)
            win.grab_set()
            win.configure(fg_color=BLACK)
            ctk.CTkLabel(win, text="SESIÓN DEL NAVEGADOR", font=(HEAVY, 18), text_color=YEL).pack(
                anchor="w", padx=22, pady=(20, 6))
            ctk.CTkLabel(win, text="IndieDL busca tu sesión de Instagram solo (DETECTAR AUTO).\nSi no puede, exportá un cookies.txt de instagram.com\ny cargalo con COOKIES.TXT.",
                         font=("Segoe UI", 12), text_color=GRAY, justify="left").pack(anchor="w", padx=22, pady=(0, 14))
            labels = {"Auto (recomendado)": "auto", "Zen Browser": "zen", "Firefox": "firefox",
                      "Helium Browser": "helium",
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
                    resolved_name = "Helium Browser" if choice == "helium" else browser
                    status.configure(text=(f"Guardado. Se usará {resolved_name} con perfil detectado." if profile else
                                           f"Guardado. Se usará {browser or 'acceso sin sesión'} con detección automática."), text_color=GREEN)
                    log(f"Preferencia de cookies guardada: {choice}; navegador resuelto={browser or 'ninguno'}; perfil_detectado={'sí' if profile else 'no'}")
                except Exception as exc:
                    status.configure(text=f"Preferencia guardada, pero falta configurar la sesión: {exc}", text_color=RED)
                self.after(1800, win.destroy)
            def import_cookies_txt():
                from tkinter import filedialog
                f = filedialog.askopenfilename(parent=win, title="Elegí el cookies.txt de instagram.com",
                                               filetypes=[("cookies.txt", "*.txt"), ("Todos", "*.*")])
                if not f:
                    return
                try:
                    txt = Path(f).read_text(encoding="utf-8-sig", errors="replace")
                    raw = txt.strip().strip('"').strip("'")
                    if raw.lower().startswith("sessionid="):
                        raw = raw.split("=", 1)[1].strip()
                    if re.fullmatch(r"[A-Za-z0-9%._:\-]{20,}", raw):
                        import time as _t
                        exp = int(_t.time()) + 365 * 24 * 3600
                        uid = raw.replace("%3A", ":").split(":")[0]
                        rows = ["# Netscape HTTP Cookie File",
                                f".instagram.com\tTRUE\t/\tTRUE\t{exp}\tsessionid\t{raw}"]
                        if uid.isdigit():
                            rows.append(f".instagram.com\tTRUE\t/\tTRUE\t{exp}\tds_user_id\t{uid}")
                        txt = "\n".join(rows) + "\n"
                    if "instagram.com" not in txt or "sessionid" not in txt:
                        status.configure(text="Ese archivo no tiene la cookie 'sessionid' de instagram.com. "
                                              "Exportalo estando logueado en Instagram.", text_color=RED)
                        return
                    APP_DIR.mkdir(parents=True, exist_ok=True)
                    COOKIES_FILE.write_text(txt, encoding="utf-8")
                    status.configure(text="cookies.txt guardado. Ya no hace falta cerrar el navegador.", text_color=GREEN)
                    self.after(1800, win.destroy)
                except Exception as exc:
                    status.configure(text=f"No pude guardar el archivo: {exc}", text_color=RED)
            def detect_here():
                status.configure(text="Buscando tu sesión de Instagram…", text_color=GRAY)

                def done(ok, st="", info=""):
                    if ok:
                        status.configure(text=f"Sesión detectada en {BROWSER_PRETTY.get(info, info)}. Listo.", text_color=GREEN)
                        self.after(1600, win.destroy)
                    else:
                        status.configure(text=auto_fail_text(st, info), text_color=RED)
                self.auto_detect_session(done, True, win)
            ctk.CTkButton(buttons, text="DETECTAR AUTO", height=38, width=112, fg_color=YEL, hover_color=YEL_H,
                          text_color=BLACK, font=(HEAVY, 11), command=detect_here).pack(side="left")
            ctk.CTkButton(buttons, text="COOKIES.TXT", height=38, width=104, fg_color="#252C33", hover_color="#343D46",
                          text_color=WHITE, font=(HEAVY, 11), command=import_cookies_txt).pack(side="left", padx=(8, 0))
            ctk.CTkButton(buttons, text="GUARDAR", height=38, width=90, fg_color="#252C33", hover_color="#343D46",
                          text_color=WHITE, font=(HEAVY, 11), command=save_choice).pack(side="right")
            ctk.CTkButton(buttons, text="CANCELAR", height=38, width=90, fg_color="#252C33", hover_color="#343D46",
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
            self._sync_clip_controls()

        def auto_detect_session(self, on_done=None, allow_prompt=True, parent=None):
            parent = parent or self
            self.msg.configure(text="Buscando tu sesión de Instagram en los navegadores…")

            def worker():
                res = import_instagram_cookies_auto(self.cfg)
                self.after(0, lambda r=res: self._auto_session_result(r, on_done, allow_prompt, parent))
            threading.Thread(target=worker, daemon=True).start()

        def _auto_session_result(self, res, on_done, allow_prompt, parent):
            ok, status, info = res
            self.msg.configure(text="Sesión de Instagram detectada." if ok else "")
            if ok:
                if on_done:
                    on_done(True, status, info)
                return
            if status == "locked" and allow_prompt:
                names = running_browser_processes(info)
                pretty = BROWSER_PRETTY.get(info, info)
                if names and messagebox.askyesno(
                        "IndieDL · Sesión de Instagram",
                        f"{pretty} está abierto y bloquea sus cookies.\n\n"
                        f"¿Querés que IndieDL lo cierre para leer tu sesión?\n"
                        f"(Guardá lo que tengas abierto; normalmente las pestañas se restauran al volver a abrirlo.)",
                        parent=parent):
                    close_browser_processes(names)
                    self.msg.configure(text="Leyendo la sesión…")
                    self.after(2500, lambda: self.auto_detect_session(on_done, False, parent))
                    return
            if on_done:
                on_done(False, status, info)

        def begin_image_selection(self, url, folder, quality):
            if self._image_dialog is not None:
                try:
                    self._image_dialog.lift()
                    return
                except Exception:
                    self._image_dialog = None
            if ("instagram.com" in url.lower() and not cookies_file_path(self.cfg)
                    and not getattr(self, "_ig_auto_attempted", False)):
                self._ig_auto_attempted = True
                self.auto_detect_session(lambda ok, *a: self.begin_image_selection(url, folder, quality))
                return
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
                    self.after(0, lambda m=msg: self.image_selection_error(m, (url, folder, quality)))

            threading.Thread(target=worker, daemon=True).start()

        def image_selection_error(self, message, ctx=None):
            self.msg.configure(text="No se pudo leer el carrusel. Revisá la sesión/cookies de Instagram.")
            self._image_dialog = None
            low = (message or "").lower()
            needs_session = any(w in low for w in ("permission denied", "login", "cookie", "401", "403",
                                                   "checkpoint", "challenge", "decrypt", "rate", "429"))
            if needs_session:
                ask = messagebox.askyesno(
                    "IndieDL · Imágenes",
                    (message or "No se encontraron imágenes accesibles.")[:500] +
                    "\n\nInstagram necesita una sesión válida.\n"
                    "¿Querés que IndieDL la busque automáticamente en tus navegadores?",
                    parent=self)
                if ask:
                    def after(ok, *a):
                        if ok and ctx:
                            self.begin_image_selection(*ctx)
                        elif not ok:
                            self.configure_cookies()
                    self.auto_detect_session(after)
            else:
                messagebox.showerror("IndieDL · Imágenes", message or "No se encontraron imágenes accesibles.", parent=self)

        def show_image_selector(self, url, folder, quality, info, entries):
            self.msg.configure(text="")
            win = ctk.CTkToplevel(self)
            self._image_dialog = win
            is_carousel = len(entries) > 1
            win.title("IndieDL · Seleccionar imágenes" if is_carousel else "IndieDL · Imagen individual")
            w, h = (700, 620) if is_carousel else (620, 430)
            win.geometry(f"{w}x{h}")
            win.minsize(560, 420)
            win.transient(self)
            win.grab_set()
            win.configure(fg_color=BLACK)
            try:
                x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
                y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
                win.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass
            heading = "CARRUSEL DE IMÁGENES" if is_carousel else "IMAGEN INDIVIDUAL"
            ctk.CTkLabel(win, text=heading, font=(HEAVY, 18), text_color=YEL).pack(anchor="w", padx=18, pady=(16, 4))
            instruction = (f"{len(entries)} imágenes detectadas. Elegí una o varias, o descargá todas."
                           if is_carousel else "Se detectó una imagen. Revisá los datos y descargala en calidad original disponible.")
            ctk.CTkLabel(win, text=instruction,
                         font=("Segoe UI", 12), text_color=GRAY).pack(anchor="w", padx=18, pady=(0, 12))
            scroll = SmoothScroll(win, fg_color="#10151A", registry=self._scroll_areas,
                                  scrollbar_button_color="#2B333C")
            scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))
            vars_ = []
            thumb_refs = []
            self._carousel_thumb_refs = thumb_refs
            for idx, entry in enumerate(entries, start=1):
                row = ctk.CTkFrame(scroll.body, fg_color="#1A2026", corner_radius=8)
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
            self._update_hist_count()
            if which == "live":
                self.after(30, self.live.scroll_to_end)

        def add_log(self, text):
            at_bottom = self.live.at_bottom()
            t = int(time.time() - self.t0)
            f = ctk.CTkFrame(self.live.body, fg_color="transparent")
            f.pack(fill="x")
            ctk.CTkLabel(f, text=f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}", font=("Consolas", 10),
                         text_color="#777", anchor="w").pack(fill="x", padx=8, pady=(8, 0))
            ctk.CTkLabel(f, text=text, font=("Segoe UI", 12), text_color=WHITE, anchor="w", justify="left",
                         wraplength=240).pack(fill="x", padx=8, pady=(0, 8))
            ctk.CTkFrame(f, fg_color="#222", height=1, corner_radius=0).pack(fill="x")
            if at_bottom:
                self.after(30, self.live.scroll_to_end)

        def _update_hist_count(self):
            try:
                n = len(self.cfg.get("history", []))
                self.r_count.configure(text=str(n),
                                       text_color="#0D1116" if n else "#7C8792",
                                       fg_color="#2A333D" if n else "transparent")
            except Exception:
                pass

        def _hist_card(self, it, parent=None):
            parent = parent or self.hist.body
            f = ctk.CTkFrame(parent, fg_color="#151B21", border_width=1,
                             border_color="#303942", corner_radius=10, cursor="hand2")
            t = it.get("title", "")
            l1 = ctk.CTkLabel(f, text=(t[:46] + "...") if len(t) > 46 else t, text_color=WHITE,
                              font=("Segoe UI Semibold", 12), anchor="w", justify="left", wraplength=240)
            l1.pack(fill="x", padx=10, pady=(8, 0))
            site_icons = {"YOUTUBE":"▶", "INSTAGRAM":"◎", "TIKTOK":"♪", "X":"𝕏", "PINTEREST":"ℙ", "LINK":"↗"}
            icon = site_icons.get(it.get("site", "LINK"), "↗")
            txt = f'{icon}  {it.get("mode", "").upper()}  ·  {it.get("site", "")}  ·  {it.get("when", "")}'
            l2 = ctk.CTkLabel(f, text=txt, text_color=GRAY, font=("Segoe UI", 10), anchor="w", justify="left")
            l2.pack(fill="x", padx=10, pady=(0, 8))

            def hover_on(_e=None):
                try:
                    f.configure(fg_color="#1A2229", border_color="#3B4652")
                except Exception:
                    pass

            def hover_off(_e=None):
                def check():
                    try:
                        x, y = f.winfo_pointerxy()
                        rx, ry = f.winfo_rootx(), f.winfo_rooty()
                        if not (rx <= x < rx + f.winfo_width() and
                                ry <= y < ry + f.winfo_height()):
                            f.configure(fg_color="#151B21", border_color="#303942")
                    except Exception:
                        pass
                self.after(24, check)

            for widget in (f, l1, l2):
                widget.bind("<Enter>", hover_on, add="+")
                widget.bind("<Leave>", hover_off, add="+")
            folder = it.get("folder", "")
            if folder:
                for widget in (f, l1, l2):
                    widget.bind("<Button-1>", lambda e, p=folder: self.open_dir(p))
            return f

        def render_hist(self):
            for w in self.hist.body.winfo_children():
                w.destroy()
            self._hist_cards = []
            self._hist_empty = None
            self._hist_items = list(self.cfg.get("history", []))
            if not self._hist_items:
                self._hist_empty = ctk.CTkLabel(
                    self.hist.body, text="Tus descargas aparecerán acá", text_color="#777",
                    font=("Segoe UI", 12), wraplength=240)
                self._hist_empty.pack(pady=60)
                self._update_hist_count()
                return
            self._hist_pending = self._hist_items[10:]
            for it in self._hist_items[:10]:
                card = self._hist_card(it)
                card.pack(fill="x", pady=4)
                self._hist_cards.append(card)
            self._update_hist_count()
            self.hist.scroll_to_top()

        def _grow_hist(self):
            try:
                if not self.winfo_exists():
                    return
            except Exception:
                return
            pending = getattr(self, "_hist_pending", None)
            if not pending:
                self._hist_pending = None
                return
            for it in pending[:12]:
                card = self._hist_card(it)
                card.pack(fill="x", pady=4)
                self._hist_cards.append(card)
            self._hist_pending = pending[12:]
            if self._hist_pending:
                self._hist_grow_job = self.after(16, self._grow_hist)
            else:
                self._hist_pending = None
                self._hist_grow_job = None

        def prepend_hist(self, item):
            if self._hist_empty is not None:
                try:
                    self._hist_empty.destroy()
                except Exception:
                    pass
                self._hist_empty = None
            card = self._hist_card(item)
            cards = getattr(self, "_hist_cards", [])
            if cards:
                card.pack(fill="x", pady=4, before=cards[0])
            else:
                card.pack(fill="x", pady=4)
            cards.insert(0, card)
            self._hist_cards = cards
            while len(cards) > 50:
                old = cards.pop()
                try:
                    old.destroy()
                except Exception:
                    pass
            self._update_hist_count()
            self.hist.scroll_to_top()

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
            self._reset_bars()
            self._set_status("●  DESCARGANDO", YEL)
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
            self._reset_bars()
            self._set_status("●  DESCARGANDO", YEL)
            self.set_stage(0, "Conectando…")
            for key in self.stat:
                self.stat[key].configure(text="-")
            self.p_msg.configure(text="")
            self.cancel.clear()
            self._last_warn = ""

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
            self._reset_bars()
            self._set_status("●  LISTO", GREEN)
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
                            if self.stage == 1:
                                self._set_bar_smooth(bar, p)
                                self.rows[self.stage]["pc"].configure(text=f"{int(round(max(0.0, min(1.0, p)) * 100))}%")
                            self._set_rbar((self.stage + max(0.0, min(1.0, p))) / max(1, len(STAGES)))
                        self.stat["sp"].configure(text=fb(sp) + "/s" if sp else "-")
                        self.stat["eta"].configure(text=ft(eta) if eta else "-")
                        self.stat["sz"].configure(text=fb(tot) if tot else fb(dl))
                        self.stat["fi"].configure(text=f"{n}/{total}" if total else "-")
                    elif kind == "log":
                        self.add_log(ev[1])
                    elif kind == "note":
                        self.p_msg.configure(text=ev[1], text_color=YEL)
                    elif kind == "warn":
                        self._last_warn = ev[1]
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
                self._hide_row_bar(r)
                r["ic"].configure(fg_color=YEL, border_width=0)
                r["il"].configure(text="✓", text_color=BLACK, font=(HEAVY, 14))
                r["tx"].configure(text_color=WHITE)
                r["pc"].configure(text="")
            self._set_rbar(1.0)
            self.b_open.configure(state="normal")
            self.show_buttons("done")
            self.btn.configure(state="normal", text="⬇  DESCARGAR")
            
            hist = self.cfg.get("history", [])
            site = site_name(self.url.get())
            item = {"title": title, "site": site, "when": time.strftime("%d/%m/%Y %H:%M"),
                    "mode": self.cur_mode, "folder": folder}
            hist.insert(0, item)
            self.cfg["history"] = hist[:50]
            self.cfg["last_saved"] = folder
            save_cfg(self.cfg)
            self.prepend_hist(item)
            
            if getattr(self, "_last_warn", ""):
                self.p_title.configure(text="Descargado con avisos")
                self.p_msg.configure(text=self._last_warn, text_color=YEL)
                self._set_status("●  AVISO", YEL)
                self._last_warn = ""
            else:
                self.p_title.configure(text="¡Completado!")
                self.p_msg.configure(text="", text_color=RED)
                self._set_status("●  COMPLETADO", GREEN)
            
            if self.cfg.get("close_when_done"):
                self.after(1800, self._on_close)

        def finish_error(self, err):
            self.busy = False
            self.show_buttons("done")
            self.btn.configure(state="normal", text="⬇  DESCARGAR")
            cancelled = "cancelado" in str(err).lower()
            self.p_msg.configure(text="" if cancelled else err, text_color=RED)
            if 0 <= self.stage < len(self.rows):
                self.rows[self.stage]["ic"].configure(fg_color="#DDD" if cancelled else RED, border_width=0)
                self.rows[self.stage]["il"].configure(text="■" if cancelled else "✕",
                                                      text_color=BLACK if cancelled else WHITE)
                self._hide_row_bar(self.rows[self.stage])
            self.p_title.configure(text="Cancelado" if cancelled else "Error")
            self._set_status("●  CANCELADO" if cancelled else "●  ERROR", GRAY if cancelled else RED)
            self._set_rbar(0.0)

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
    if "--register-only" in sys.argv:
        try:
            if os.name == "nt":
                register()
                log("Protocolo ytdl:// registrado por el instalador.")
        except Exception as e:
            log(f"No se pudo registrar ytdl://: {e}")
        sys.exit(0)

    build_app()
