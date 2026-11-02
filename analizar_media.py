#!/usr/bin/env python3
"""IndieDL · Analizador de archivos de video.

Uso:  python analizar_media.py "C:\\ruta\\video.mp4" [otro.mp4 ...]
      (también puedes arrastrar el archivo encima de este .py)

Dice qué trae el archivo (video, audio, tiempos) y, sobre todo, si el audio
SUENA de verdad o está en silencio, y qué puede estar fallando en DaVinci.
No modifica ni escribe nada.
"""
import json, os, re, shutil, subprocess, sys

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def find_tools():
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ff = None
    if not ff:
        loc = os.environ.get("LOCALAPPDATA", "")
        for cand in (os.path.join(loc, "IndieDL", "ffmpeg.exe"), os.path.join(loc, "IndieDL", "bin", "ffmpeg.exe")):
            if os.path.isfile(cand):
                ff = cand
                break
    fp = shutil.which("ffprobe")
    if not fp and ff:
        side = os.path.join(os.path.dirname(ff), "ffprobe.exe" if os.name == "nt" else "ffprobe")
        fp = side if os.path.isfile(side) else None
    return ff, fp


def run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=NO_WINDOW, timeout=timeout)
    return (r.stderr or "") + (r.stdout or "")


def last_time(text):
    ts = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", text)
    if not ts:
        return None
    h, m, s = ts[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def probe_json(fp, path):
    try:
        out = subprocess.run([fp, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             creationflags=NO_WINDOW, timeout=60).stdout
        return json.loads(out)
    except Exception:
        return None


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fps_of(frac):
    try:
        a, b = frac.split("/")
        return float(a) / float(b) if float(b) else None
    except Exception:
        return None


def analyze(ff, fp, path):
    ok, warn, bad = [], [], []
    print("=" * 70)
    print("ARCHIVO:", path)
    if not os.path.isfile(path):
        print("  No existe ese archivo.")
        return
    print("TAMAÑO :", f"{os.path.getsize(path) / 1048576:.2f} MB")
    import unicodedata
    stem = os.path.basename(path)
    if any(ord(c) > 0xFFFF or c in "\ufe0e\ufe0f" or unicodedata.category(c)[0] == "C"
           or unicodedata.category(c) in ("So", "Sk") for c in stem):
        warn.append("El nombre tiene emojis/símbolos: DaVinci en Windows suele marcar Media Offline por eso. Renómbralo.")

    info = probe_json(fp, path) if fp else None
    v = a_list = None
    if info:
        streams = info.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_list = [s for s in streams if s.get("codec_type") == "audio"]
        fmt = info.get("format", {})
        print("CONTENEDOR:", fmt.get("format_name"), "| duración:", fmt.get("duration"), "s")
    else:
        txt = run([ff, "-hide_banner", "-i", path])
        print(txt.strip().splitlines()[0] if txt.strip() else "")
        for line in txt.splitlines():
            if "Stream #" in line:
                print("  ", line.strip())
        a_list = ["audio"] if "Audio:" in txt else []
        print("  (ffprobe no está disponible: análisis más corto)")

    # ---------- VIDEO ----------
    print("\n--- VIDEO ---")
    if v:
        codec = v.get("codec_name")
        print(f"códec {codec} ({v.get('profile')}) · {v.get('width')}x{v.get('height')} · "
              f"{v.get('pix_fmt')} · {v.get('avg_frame_rate')} fps")
        if codec == "hevc":
            warn.append("Video HEVC/H.265: DaVinci gratuito en Windows puede no leerlo o pedir GPU compatible.")
        elif codec not in ("h264",):
            warn.append(f"Video {codec}: no es H.264, DaVinci puede marcarlo Media Offline (AV1/VP9 es lo típico).")
        else:
            ok.append("Video H.264 estándar.")
        if v.get("pix_fmt") not in (None, "yuv420p"):
            warn.append(f"Formato de píxel {v.get('pix_fmt')} (no es 8-bit 4:2:0): DaVinci gratuito puede rechazarlo.")
        avg, rr = fps_of(v.get("avg_frame_rate", "")), fps_of(v.get("r_frame_rate", ""))
        if avg and rr and abs(avg - rr) > 0.5:
            warn.append(f"Cuadros por segundo variables (promedio {avg:.2f} vs base {rr:.2f}): puede desincronizar el audio en DaVinci.")
    elif info:
        bad.append("No hay pista de video.")

    # ---------- AUDIO ----------
    print("\n--- AUDIO ---")
    if not a_list:
        bad.append("El archivo NO tiene pista de audio.")
    else:
        if len(a_list) > 1:
            warn.append(f"Tiene {len(a_list)} pistas de audio: DaVinci puede mostrar la equivocada.")
        if info:
            s = a_list[0]
            print(f"códec {s.get('codec_name')} ({s.get('profile')}) · {s.get('sample_rate')} Hz · "
                  f"{s.get('channels')} canales ({s.get('channel_layout')}) · {s.get('bit_rate')} bps")
            prof = (s.get("profile") or "").upper()
            if s.get("codec_name") != "aac":
                warn.append(f"Audio {s.get('codec_name')} (no es AAC): DaVinci puede no leerlo en MP4.")
            elif "HE" in prof:
                warn.append("Audio HE-AAC: DaVinci suele dar silencio con este perfil.")
            elif prof not in ("LC", ""):
                warn.append(f"Perfil AAC {prof}: no es AAC-LC estándar.")
            else:
                ok.append("Audio AAC-LC estándar.")
            sr = fnum(s.get("sample_rate"))
            if sr and sr not in (44100, 48000):
                warn.append(f"Frecuencia {int(sr)} Hz: lo normal es 44100 o 48000.")
            if (s.get("channels") or 0) > 2:
                warn.append(f"{s.get('channels')} canales: DaVinci puede configurarlos mal.")
            if v:
                vs, as_ = fnum(v.get("start_time")), fnum(s.get("start_time"))
                if vs is not None and as_ is not None and abs(vs - as_) > 0.1:
                    warn.append(f"El audio empieza a {as_:.3f}s y el video a {vs:.3f}s: desfase de inicio.")
                vd, ad = fnum(v.get("duration")), fnum(s.get("duration"))
                if vd and ad and ad < vd * 0.9:
                    warn.append(f"El audio dura {ad:.1f}s y el video {vd:.1f}s: el audio termina antes.")

        # nivel real del sonido
        out = run([ff, "-hide_banner", "-i", path, "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"])
        mean = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", out)
        peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", out)
        if mean and peak:
            m = float("-inf") if mean.group(1) == "-inf" else float(mean.group(1))
            p = float("-inf") if peak.group(1) == "-inf" else float(peak.group(1))
            print(f"volumen medio {mean.group(1)} dB · pico {peak.group(1)} dB")
            if p == float("-inf") or p < -60:
                bad.append("EL AUDIO ESTÁ EN SILENCIO dentro del propio archivo (no es un problema de DaVinci). "
                           "La descarga vino sin sonido; hay que bajarlo de nuevo o de otra fuente.")
            elif p < -30:
                warn.append(f"Audio muy bajo (pico {p} dB).")
            else:
                ok.append(f"El audio SUENA (pico {p} dB): el sonido está dentro del archivo.")
        else:
            warn.append("No pude medir el volumen del audio (¿no se pudo decodificar?). "
                        "Eso suele significar que el audio está dañado o es de un tipo no estándar.")
            tail = [l for l in out.splitlines() if "rror" in l or "nvalid" in l][-2:]
            for t in tail:
                print("   ffmpeg:", t.strip()[:150])

    # ---------- VEREDICTO ----------
    print("\n--- RESULTADO ---")
    for t in ok:
        print("  OK     ", t)
    for t in warn:
        print("  AVISO  ", t)
    for t in bad:
        print("  PROBLEMA", t)
    if bad:
        print("\nConclusión: el archivo tiene un problema propio. Convertir el códec no lo arregla si el audio ya viene mudo.")
    elif warn:
        print("\nConclusión: puede fallar en DaVinci por los avisos de arriba.")
    else:
        print("\nConclusión: el archivo es correcto y debería leerse bien en DaVinci.")


def main():
    ff, fp = find_tools()
    if not ff:
        print("No encontré ffmpeg. Instálalo o ejecuta este script con el Python de IndieDL:")
        print(r'  %LOCALAPPDATA%\IndieDL\venv\Scripts\python.exe analizar_media.py "video.mp4"')
        input("Enter para salir...")
        return
    paths = sys.argv[1:]
    if not paths:
        p = input("Arrastra aquí el video y pulsa Enter: ").strip().strip('"')
        paths = [p] if p else []
    for p in paths:
        analyze(ff, fp, p)
    if os.name == "nt":
        input("\nEnter para cerrar...")


if __name__ == "__main__":
    main()