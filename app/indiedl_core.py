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
    "open_folder_done": False,
    "usar_parakeet": True,
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
    current = None
    
    for k, v in parse_qsl(m.group(1), keep_blank_values=True):
        if k == "u":
            u = clean_url(v)
            if u and u not in seen:
                seen.add(u)
                current = {"url": u, "title": "", "s": None, "e": None}
                items.append(current)
        elif k == "t" and current and not current["title"]:
            current["title"] = v.strip()[:120]
        elif k == "s" and current:
            try: current["s"] = int(v)
            except ValueError: pass
        elif k == "e" and current:
            try: current["e"] = int(v)
            except ValueError: pass
            
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

def _netscape_cookie_file(path):
    """True si `path` parece un cookies.txt en formato Netscape (7 columnas)."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
            if not (first.startswith("# Netscape HTTP Cookie File")
                    or first.startswith("# HTTP Cookie File")):
                return False
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                return len(line.split("\t")) >= 7
    except OSError:
        return False
    return False


# ── Sesión de Instagram: guardado seguro (DPAPI) + detección automática ──
IG_COOKIES_BIN = APP_DIR / "instagram_cookies.bin"
_IG_MATERIAL = {"path": None}  # ruta del cookies.txt temporal de esta corrida


def _dpapi_ba(data, proteger=True):
    """Cifra/descifra bytes con DPAPI de Windows (CurrentUser).

    La clave la administra Windows y está atada a la cuenta de usuario de esta
    PC: copiar el .bin a otra máquina o a otro usuario vuelve el contenido
    inservible. No necesita que nadie recuerde ninguna contraseña.
    """
    import ctypes
    import ctypes.wintypes as wt

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def _entrada(b):
        buf = (ctypes.c_byte * max(1, len(b))).from_buffer_copy(bytes(b))
        return _BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf

    def _salida():
        return _BLOB(0, None)

    def _mantener(*objs):
        # evita que el GC libere los buffers antes de la llamada a la API
        return objs

    crypt32 = ctypes.windll.crypt32
    if proteger:
        fn, firma = crypt32.CryptProtectData, (
            ctypes.POINTER(_BLOB), wt.LPCWSTR, ctypes.POINTER(_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(_BLOB))
    else:
        fn, firma = crypt32.CryptUnprotectData, (
            ctypes.POINTER(_BLOB), ctypes.POINTER(wt.LPCWSTR), ctypes.POINTER(_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(_BLOB))
    fn.argtypes = firma
    fn.restype = ctypes.c_bool

    if proteger:
        entrada, buf = _entrada(data)
        salida = _salida()
        ok = fn(ctypes.byref(entrada), None, None, None, None, 1, ctypes.byref(salida))
    else:
        entrada, buf = _entrada(data)
        salida = _salida()
        desc = wt.LPCWSTR()
        ok = fn(ctypes.byref(entrada), ctypes.byref(desc), None, None, None, 1, ctypes.byref(salida))
    _mantener(buf)
    if not ok:
        raise OSError("DPAPI %s falló (WinError %s)" % (
            "cifrado" if proteger else "descifrado", ctypes.GetLastError()))
    res = bytes(ctypes.string_at(salida.pbData, salida.cbData))
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree(salida.pbData)
    return res


def _ig_guardar_seguro(texto):
    """Guarda el cookies.txt de Instagram cifrado con DPAPI (instagram_cookies.bin)."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    binario = _dpapi_ba(texto.encode("utf-8"), proteger=True)
    tmp = str(IG_COOKIES_BIN) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(binario)
    os.replace(tmp, IG_COOKIES_BIN)
    log("Cookies de Instagram guardadas cifradas (instagram_cookies.bin; "
        "solo se abren con tu cuenta de Windows en esta PC).")


def _ig_cargar_seguro():
    """Texto del cookies.txt de Instagram desde el almacenamiento cifrado."""
    if not IG_COOKIES_BIN.is_file():
        return ""
    try:
        return _dpapi_ba(IG_COOKIES_BIN.read_bytes(), proteger=False).decode("utf-8", errors="replace")
    except Exception as exc:
        log(f"No pude descifrar instagram_cookies.bin ({type(exc).__name__}: {exc}); "
            "el archivo quedó dañado o vino de otra PC. Reimportá la sesión.")
        return ""


def _ig_limpiar_material():
    p = _IG_MATERIAL.get("path")
    if p:
        try:
            os.remove(p)
        except OSError:
            pass
        _IG_MATERIAL["path"] = None


def _ig_limpiar_stales():
    """Borra cookies.txt de trabajo temporales de corridas anteriores."""
    try:
        for p in APP_DIR.glob("ig_cookies_trabajo_*.txt"):
            try:
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _ig_materializar():
    """Crea (una vez por corrida) el cookies.txt temporal que usan yt-dlp y gallery-dl."""
    if _IG_MATERIAL.get("path"):
        return _IG_MATERIAL["path"]
    texto = _ig_cargar_seguro()
    if not texto or "instagram" not in texto or "sessionid" not in texto:
        return None
    try:
        import atexit
        import tempfile
        fd, path = tempfile.mkstemp(prefix="ig_cookies_trabajo_", suffix=".txt", dir=str(APP_DIR))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto if texto.endswith("\n") else texto + "\n")
        _IG_MATERIAL["path"] = path
        atexit.register(_ig_limpiar_material)
        return path
    except OSError as exc:
        log(f"No pude materializar el cookies.txt de trabajo ({exc}).")
        return None


def _ig_migrar_txt():
    """Pasa el instagram_cookies.txt plano (import manual viejo) al .bin cifrado y lo borra."""
    try:
        if not (COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 0):
            return
        if not _netscape_cookie_file(COOKIES_FILE):
            return
        texto = COOKIES_FILE.read_text(encoding="utf-8", errors="replace")
        if "instagram" in texto and "sessionid" in texto:
            _ig_guardar_seguro(texto)
            try:
                COOKIES_FILE.unlink()
            except OSError:
                pass
            log("Cookies guardadas en formato cifrado; el instagram_cookies.txt plano fue eliminado.")
    except Exception as exc:
        log(f"Migración de cookies no crítica: {type(exc).__name__}: {exc}")


def _fecha_legible(ts):
    import time as _t
    try:
        ts = int(ts)
        if ts <= 0:
            return ""
        return _t.strftime("%d %b %Y", _t.localtime(ts))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def sesion_ig_estado():
    """Estado de la sesión guardada: (tiene_sesion, vencida, n_cookies, vence_legible)."""
    texto = _ig_cargar_seguro()
    if not texto:
        try:
            if COOKIES_FILE.is_file() and _netscape_cookie_file(COOKIES_FILE):
                texto = COOKIES_FILE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            texto = ""
    if not texto or "sessionid" not in texto:
        return False, False, 0, ""
    import time as _t
    n, vence, ahora = 0, None, int(_t.time())
    for line in texto.splitlines():
        cols = line.strip().split("\t")
        # Netscape: 0=dominio, 4=expiración, 5=nombre, 6=valor
        if len(cols) >= 7 and "instagram.com" in cols[0] and cols[5] and not cols[5].startswith("#"):
            n += 1
            if cols[5] == "sessionid":
                try:
                    vence = int(cols[4])
                except (TypeError, ValueError):
                    vence = None
    vencida = bool(vence and int(vence) <= ahora)
    return True, vencida, n, _fecha_legible(vence) if vence else ""


def asegurar_sesion_ig_auto(cfg=None, forzar=False):
    """Importa la sesión de Instagram desde los navegadores si falta o venció.

    No abre diálogos ni cierra navegadores: eso queda para el flujo interactivo
    de la UI (auto_detect_session). Idóneo para correr al abrir la app.
    Devuelve (ok, status, info) como import_instagram_cookies_auto.
    """
    _ig_limpiar_stales()
    _ig_migrar_txt()
    tiene, vencida, n, vence = sesion_ig_estado()
    if tiene and not vencida and not forzar:
        log(f"Sesión de Instagram vigente ({n} cookies" + (f", vence {vence}" if vence else "") + ").")
        return True, "ok", "vigente"
    if tiene and vencida:
        log(f"Sesión de Instagram vencida ({vence}); buscando una nueva en tus navegadores…")
    else:
        log("No hay sesión de Instagram guardada; busco en tus navegadores…")
    ok, status, info = import_instagram_cookies_auto(cfg)
    if ok and info != "vigente":
        log(f"Sesión de Instagram importada automáticamente desde {BROWSER_PRETTY.get(info, info)}.")
    elif status == "locked":
        log(f"No pude leer la sesión: {BROWSER_PRETTY.get(info, info)} está abierto y bloquea sus cookies. "
            "Cerralo y volvé a abrir IndieDL (o importá cookies.txt en ⚙ SESIÓN).")
    elif status == "nosession":
        log("Ningún navegador tiene sesión de Instagram: iniciá sesión en instagram.com "
            "en tu navegador y volvé a abrir IndieDL.")
    elif not ok:
        log(f"No pude importar la sesión automáticamente: {info}")
    return ok, status, info

def yt_cookie_opts(url, cfg=None):
    opts = {}
    u = str(url).lower()

    if "youtube.com" in u or "youtu.be" in u:
        browser_choice = str((cfg or {}).get("cookies_browser", "auto") or "auto").lower()
        if browser_choice != "none":
            if browser_choice == "auto":
                candidates = browser_profile_candidates()
                # Incluye zen y helium que antes se ignoraban
                for c in candidates:
                    raw = c["browser"]
                    if raw in ("zen", "firefox"):
                        b = "firefox"
                    elif raw == "helium":
                        b = "chromium"
                    elif raw in ("chrome", "edge", "brave"):
                        b = raw
                    else:
                        continue
                    opts["cookiesfrombrowser"] = (b, c["profile"], None, None)
                    log(f"YouTube cookies: usando {raw} (auto) perfil={c['profile'][-40:]}")
                    break
            elif browser_choice in ("chrome", "edge", "firefox", "brave", "zen", "helium"):
                b = browser_choice
                if b == "helium":
                    b = "chromium"
                if b == "zen":
                    b = "firefox"
                # Intentar encontrar el perfil real
                for c in browser_profile_candidates():
                    if c["browser"] == browser_choice:
                        opts["cookiesfrombrowser"] = (b, c["profile"], None, None)
                        log(f"YouTube cookies: usando {b} (manual) perfil={c['profile'][-40:]}")
                        break
                else:
                    opts["cookiesfrombrowser"] = (b, None, None, None)
                    log(f"YouTube cookies: usando {b} (manual, perfil por defecto)")

    elif "instagram.com" in u:
        # Instagram necesita sesión (cookies) para ver la mayoría de posts:
        # sin ellas yt-dlp responde "This content isn't available to everyone".
        file_ok = cookies_file_path(cfg)
        if file_ok:
            opts["cookiefile"] = file_ok
            log("Instagram cookies: usando instagram_cookies.txt")
        else:
            log("Instagram cookies: no hay archivo válido. Importá tu sesión "
                "en la app (⚙ SESIÓN) o el post puede fallar con "
                "'This content isn't available to everyone'.")

    if (("youtube.com" in u or "youtu.be" in u) and YT_COOKIES.is_file()
            and YT_COOKIES.stat().st_size > 0):
        if _netscape_cookie_file(YT_COOKIES):
            opts["cookiefile"] = str(YT_COOKIES)
    return opts

def cookies_file_path(cfg=None):
    """Ruta de un cookies.txt de Instagram usable por yt-dlp y gallery-dl.

    Prioridad: el .bin cifrado (se materializa a un txt temporal durante la
    corrida) > el instagram_cookies.txt plano de antes (sin migrar).
    Devuelve None si no hay sesión guardada.
    """
    path = _ig_materializar()
    if path:
        return path
    try:
        if COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 0:
            if _netscape_cookie_file(COOKIES_FILE):
                return str(COOKIES_FILE)
            log("instagram_cookies.txt no tiene formato Netscape válido; se ignora.")
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
            adv.GetTokenInformation(tok, 25, None, 0, ctypes.byref(need))
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
    _ig_migrar_txt()
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
                _ig_guardar_seguro("\n".join(rows) + "\n")
            except Exception as exc:
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

def gallery_dl_download(url, folder, cfg, q, cancel, image_indices=None, is_batch=False):
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
        proc = subprocess.Popen(a, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW)
        # Matar el proceso si se cancela.
        def _watcher():
            while proc.poll() is None:
                if cancel.is_set():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return
                time.sleep(0.2)
        threading.Thread(target=_watcher, daemon=True).start()
        try:
            out, err = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            out, err = proc.communicate()
        # Objeto compatible con subprocess.CompletedProcess
        class _R:
            pass
        r = _R()
        r.returncode = proc.returncode
        r.stdout = out
        r.stderr = err
        return r
    proc = _run(True)
    if cancel.is_set():
        raise RuntimeError("Cancelado")
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
    if not is_batch:
        q.put(("done", folder, title))
    else:
        return folder, title

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

def run_download(url, mode, folder, cfg, q, quality, cancel, section=None, image_indices=None, cached_info=None, is_batch=False):
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
            gallery_dl_download(url, folder, cfg, q, cancel, image_indices, is_batch=is_batch)
            if not is_batch:
                return
            else:
                return folder, "Imágenes descargadas"

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
            "noplaylist": mode != "image",
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "windowsfilenames": True,
            "progress_hooks": [hook],
            "postprocessor_hooks": [phook],
            # ─── Optimizaciones de red ───
            "concurrent_fragment_downloads": 10,
            "http_chunk_size": 10 * 1024 * 1024,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 3,
            "file_access_retries": 3,
            "continuedl": True,
            "paths": {"home": str(TEMP_DIR), "temp": str(TEMP_DIR)},
        }
        # http_chunk_size rompe el downloader HLS (Pinterest: "Conflicting range")
        if "youtube.com" not in str(url).lower() and "youtu.be" not in str(url).lower():
            opts.pop("http_chunk_size", None)
        if ff:
            opts["ffmpeg_location"] = ff
        opts.update(yt_cookie_opts(url, cfg))
        if mode == "video":
            opts.update(format=vfmt(quality), merge_output_format="mp4")
            if section:
                opts["download_sections"] = [f"*{section[0]}-{section[1]}"]
                opts["force_keyframes_at_cuts"] = True
        elif mode == "audio":
            opts.update({
                "format": ("bv*[vcodec^=avc1]+ba[acodec^=mp4a]/bv*+ba/b"),
                "merge_output_format": "mp4",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": quality or AUDIO_CODEC, "preferredquality": AUDIO_QUALITY}],
            })
            if section:
                opts["download_sections"] = [f"*{section[0]}-{section[1]}"]
                opts["force_keyframes_at_cuts"] = True
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
            try:
                with yt_dlp.YoutubeDL(opts) as y:
                    res = y.extract_info(url, download=True)
            except Exception as exc:
                msg_exc = str(exc).lower()
                es_ig = "instagram.com" in str(url).lower()
                es_cookies_navegador = "cookiesfrombrowser" in opts
                if ("cookie" in msg_exc and es_cookies_navegador
                        and not es_ig):
                    # Solo tiene sentido para cookies de navegador (pueden
                    # estar bloqueadas por otro proceso). Con archivo de
                    # cookies relanzar idéntico no arregla nada.
                    q.put(("log", "No pude leer las cookies del navegador (¿abierto?); reintento sin cookies."))
                    opts.pop("cookiesfrombrowser", None)
                    opts.pop("cookiefile", None)
                    with yt_dlp.YoutubeDL(opts) as y:
                        res = y.extract_info(url, download=True)
                else:
                    if es_ig and "isn't available" in msg_exc and opts.get("cookiefile"):
                        q.put(("log", "Instagram devolvió 'content isn't available' AUN con cookies: "
                                      "la sesión puede estar vencida. Reimportá tu sesión en ⚙ SESIÓN."))
                    raise

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
        if mode in ("video", "audio"):
            q.put(("log", "Formato de descarga: " + str(opts.get("format") or "-")))
            res_fmt = (res or {}).get("format") if isinstance(res, dict) else None
            q.put(("log", "Formato resuelto: " + str(res_fmt or (res or {}).get("format_id") or "-")))
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
        
        if not is_batch:
            q.put(("done", folder_guardado, st["title"] or (res or {}).get("title") or url))
        else:
            return folder_guardado, st["title"] or (res or {}).get("title") or url
            
    except Exception as e:
        err_text = str(e).replace("ERROR: ", "").strip()
        log(f"download {url}: {e!r}\n{traceback.format_exc()}")
        low = err_text.lower()

        if "sign in to confirm your age" in low or "confirm your age" in low:
            err_text = (
                "YouTube pide verificación de edad para este video. "
                "IndieDL intentó usar tus cookies del navegador pero no las aceptó. "
                "Soluciones: (1) Abrí el video en tu navegador e iniciá sesión en YouTube. "
                "(2) En IndieDL, abrí ⚙ SESIÓN y elegí el navegador donde estás logueado. "
                "(3) Si usás Zen o Helium, elegilo explícitamente (no 'Auto'). "
                "(4) Reintentá."
            )
        elif "this video is not available" in low or "video unavailable" in low or "private video" in low:
            err_text = (
                "Este video no está disponible en YouTube. "
                "Razones posibles: el video fue eliminado por el creador, "
                "es privado, o tiene restricción geográfica. "
                "Probá con otro enlace."
            )
        elif "read timed out" in low or "timed out" in low:
            err_text = (
                "Los servidores de YouTube no respondieron a tiempo (read timeout). "
                "IndieDL ya reintentó 10 veces. Posibles causas: "
                "(1) Tu conexión a internet está lenta o inestable. "
                "(2) YouTube te está bloqueando por hacer muchas descargas seguidas. "
                "(3) La red de tu ISP tiene problemas con googlevideo.com. "
                "Esperá unos minutos y reintentá."
            )
        elif "unexpected response from webpage request" in low or "solve_challenge" in low or "http error 403" in low:
            if "tiktok.com" in url.lower():
                err_text = (
                    "TikTok rechazó la conexión. Posibles causas: "
                    "(1) VPN/proxy. (2) Bloqueo temporal de tu IP. "
                    "Probá otra red y reintentá."
                )
        elif not err_text:
            err_text = (
                f"Error interno de yt-dlp: {type(e).__name__}. "
                r"Detalle en %LOCALAPPDATA%\IndieDL\indiedl.log"
            )

        if not is_batch:
            q.put(("err", err_text[:500]))
        else:
            raise RuntimeError(err_text[:500])

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