"""Indie Now DL - interfaz grafica (CustomTkinter)."""
import ctypes
import io
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from indiedl_core import *  # noqa: F401,F403

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
        self._prefs_ready = False
        self._finish_seq = 0
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
        self.batch_items_ui = []
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
        self.after(600, self._sesion_arranque)

    def _sesion_arranque(self):
        """Detecta la sesión de Instagram al abrir la app, en silencio.

        Busca en los navegadores (Zen/Firefox/Helium/Chrome/Edge/Brave) si no
        hay sesión guardada o si la guardada venció; guarda el resultado
        cifrado. No cierra navegadores ni abre ventanas: si algo falta, avisa
        sin molestar y se reintenta al descargar.
        """
        def worker():
            ok, status, info = asegurar_sesion_ig_auto(getattr(self, "cfg", None) or {})
            if ok and info != "vigente":
                def avisar():
                    self.msg.configure(text=f"Sesión de Instagram detectada automáticamente "
                                            f"({BROWSER_PRETTY.get(info, info)}).")
                    self.after(6000, lambda: self.msg.cget("text").startswith("Sesión de Instagram detectada")
                               and self.msg.configure(text=""))
                self.after(0, avisar)
            elif status == "nosession":
                self.after(0, lambda: self.msg.configure(
                    text="Sin sesión de Instagram: iniciá sesión en instagram.com y reiniciá IndieDL, "
                         "o importá cookies.txt en ⚙ SESIÓN."))
        threading.Thread(target=worker, daemon=True).start()

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
            if getattr(self, "busy", False):
                try:
                    self.cancel.set()
                except Exception:
                    pass
        except Exception:
            pass
        # Marcar items de la cola como pausados/cancelados al cerrar
        if getattr(self, "batch_mode", False) and hasattr(self, "batch_items_ui"):
            for ui in self.batch_items_ui:
                try:
                    st = ui["status"]
                    if st.cget("text") not in ("Completado",):
                        st.configure(text="Pausado", text_color=GRAY)
                        ui["icon"].configure(text="■", text_color=GRAY)
                except Exception:
                    pass
        try:
            if getattr(self, "_close_job", None):
                self.after_cancel(self._close_job)
                self._close_job = None
        except Exception:
            pass
        try:
            if hasattr(self, "v_ask"):
                self.cfg["ask_folder"] = self.v_ask.get()
                self.cfg["close_when_done"] = self.v_close.get()
                self.cfg["open_folder_done"] = self.v_open.get()
                self.cfg["pcm_resolve"] = self.v_pcm.get()
                self.cfg["usar_parakeet"] = self.v_parakeet.get()
                folder = self.folder.get().strip()
                if folder:
                    self.cfg["last_dir"] = folder
                save_cfg(self.cfg)
        except Exception:
            pass
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
        left_stack.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right_stack = ctk.CTkFrame(self.form, fg_color="transparent")
        right_stack.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

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
        self.preview.pack(fill="both", expand=True, pady=(10, 0))
        self.preview.grid_columnconfigure(0, weight=1)
        self.preview.grid_rowconfigure(0, weight=1)
        self.preview.grid_rowconfigure(5, weight=1)
        self.platform_icon = ctk.CTkLabel(self.preview, text="", image=self.make_platform_logo("LINK"),
            width=56, height=56, fg_color="transparent", corner_radius=10)
        self.platform_icon.grid(row=1, column=0, pady=(6, 4))
        self.thumbnail_label = ctk.CTkLabel(self.preview, text="", width=300, height=169,
            fg_color="#20272E", corner_radius=8)
        self.thumbnail_label.grid(row=2, column=0, pady=(2, 10))
        self.thumbnail_image = None
        self.preview_title = ctk.CTkLabel(self.preview, text="Vista previa del contenido",
            text_color=WHITE, font=("Segoe UI Semibold", 16), anchor="center",
            justify="center", wraplength=420)
        self.preview_title.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 4))
        self.preview_meta = ctk.CTkLabel(self.preview, text="Pegá un enlace para detectar plataforma y detalles",
            text_color=GRAY, font=("Segoe UI", 12), anchor="center", justify="center", wraplength=440)
        self.preview_meta.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 6))
        self._meta_job = None

        blk = self.card(right_stack)
        self.blk = blk
        blk.pack(fill="both", expand=True, pady=(14, 0))
        blk.grid_columnconfigure(2, weight=1)
        for _r in (0, 2, 4, 6):
            blk.grid_rowconfigure(_r, weight=1)

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
                                      dropdown_hover_color=YEL, font=(HEAVY, 13), dropdown_font=("Segoe UI", 13),
                                      command=self._quality_changed)
        self.menu.grid(row=4, column=2, sticky="ew", padx=(0, 14))
        sep(5)

        rowtitle(6, "5", "⚙ Opciones")
        op = ctk.CTkFrame(blk, fg_color="transparent")
        op.grid(row=6, column=2, sticky="w")
        self.v_ask = ctk.BooleanVar(value=self.cfg["ask_folder"])
        self.v_close = ctk.BooleanVar(value=self.cfg["close_when_done"])
        self.v_pcm = ctk.BooleanVar(value=self.cfg.get("pcm_resolve", False))
        self.v_open = ctk.BooleanVar(value=self.cfg.get("open_folder_done", False))
        self.v_parakeet = ctk.BooleanVar(value=self.cfg.get("usar_parakeet", True))
        for text, var in (("▣  Preguntar carpeta", self.v_ask), ("✓  Cerrar al terminar", self.v_close),
                          ("▤  Abrir carpeta al terminar", self.v_open),
                          ("♫  Audio PCM (.mov)", self.v_pcm),
                          ("⚡  Usar Parakeet Ultra (Experimental)", self.v_parakeet)):
            ctk.CTkCheckBox(op, text=text, variable=var, text_color=WHITE, font=("Segoe UI Semibold", 12),
                            fg_color=YEL, hover_color=YEL_H, border_color=BLACK, checkmark_color=BLACK,
                            border_width=2, corner_radius=3, checkbox_width=20,
                            checkbox_height=20).pack(anchor="w", pady=2)

        # Cada cambio de una opción se guarda al instante en config.json.
        for var, key in (("v_ask", "ask_folder"), ("v_close", "close_when_done"),
                         ("v_open", "open_folder_done"), ("v_pcm", "pcm_resolve"),
                         ("v_parakeet", "usar_parakeet")):
            getattr(self, var).trace_add(
                "write", lambda *_a, v=getattr(self, var), k=key: self._pref_changed(k, v.get()))
        self._prefs_ready = True
        self.folder.bind("<FocusOut>",
                         lambda _e: self._pref_changed("last_dir", self.folder.get().strip()))

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

    def _cancel_bar_anim(self, bar):
        job = self._bar_jobs.pop(bar, None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        try:
            bar.stop()
        except Exception:
            pass

    def _hide_row_bar(self, row):
        self._cancel_bar_anim(row["bar"])
        try:
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
        self._sync_mode_controls(True)

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

    def _pref_changed(self, key, value):
        """Guarda una preferencia en cuanto el usuario la cambia."""
        if not getattr(self, "_prefs_ready", False):
            return
        if not value and key == "last_dir":
            return
        if self.cfg.get(key) == value:
            return
        self.cfg[key] = value
        save_cfg(self.cfg)

    def _quality_changed(self, value):
        self._pref_changed("audio_fmt" if self.cur_mode == "audio" else "video_q", value)

    @staticmethod
    def _is_short_form(url):
        u = (url or "").lower()
        return ("/shorts/" in u or "/reel/" in u or "/reels/" in u or "tiktok.com/" in u)

    def _sync_mode_controls(self, force_video=False):
        """En Reels, Shorts y TikTok el audio no tiene sentido: se oculta."""
        if not hasattr(self, "b_audio"):
            return
        if getattr(self, "batch_mode", False):
            self.b_audio.grid()
            return
        try:
            short = self._is_short_form(self.url.get())
        except Exception:
            short = False
        if short:
            # Un enlace explícito de audio (ytdl://audio/...) se respeta y se muestra.
            if self.cur_mode == "audio" and not force_video:
                self.b_audio.grid()
            else:
                self.b_audio.grid_remove()
                if force_video and self.cur_mode == "audio":
                    self.set_mode("video")
        else:
            self.b_audio.grid()

    def _resolve_folder(self):
        """Devuelve la carpeta elegida; pide una si 'Preguntar carpeta' esta activo."""
        folder = self.folder.get().strip()
        if not self.v_ask.get():
            return folder
        chosen = filedialog.askdirectory(
            parent=self, title="Elegí la carpeta de destino",
            initialdir=folder or self.cfg.get("last_dir") or str(Path.home()))
        if not chosen:
            return None
        folder = os.path.normpath(chosen)
        self.folder.delete(0, "end")
        self.folder.insert(0, folder)
        return folder

    def _youtube_video_id(self, url):
        import re as _re
        m = _re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{6,})", str(url or ""))
        return m.group(1) if m else None

    def _youtube_oembed_info(self, url):
        try:
            from urllib.request import Request, urlopen
            import json as _json
            import urllib.parse as _up
            oembed_url = "https://www.youtube.com/oembed?url=" + _up.quote(url, safe="") + "&format=json"
            req = Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=8) as resp:
                data = _json.loads(resp.read().decode("utf-8", "replace"))
            vid = self._youtube_video_id(url)
            thumb = data.get("thumbnail_url")
            if not thumb and vid:
                thumb = "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid
            info = {
                "title": data.get("title") or "Contenido de YouTube",
                "uploader": data.get("author_name") or "YouTube",
                "channel": data.get("author_name") or "YouTube",
                "duration": None,
                "width": data.get("thumbnail_width"),
                "height": data.get("thumbnail_height"),
                "ext": "mp4",
                "thumbnail": thumb,
                "thumbnails": [{"url": thumb}] if thumb else [],
                "description": "",
            }
            return info
        except Exception as exc:
            log("youtube oembed %s: %r" % (url, exc))
            vid = self._youtube_video_id(url)
            if vid:
                return {
                    "title": "Contenido de YouTube",
                    "uploader": "YouTube",
                    "channel": "YouTube",
                    "duration": None,
                    "width": None,
                    "height": None,
                    "ext": "mp4",
                    "thumbnail": "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid,
                    "thumbnails": [{"url": "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid}],
                    "description": "",
                }
            return None

    def _metadata_referer(self, url):
        u = (url or "").lower()
        if "tiktok.com" in u:
            return "https://www.tiktok.com/"
        if "youtube.com" in u or "youtu.be" in u:
            return "https://www.youtube.com/"
        if "instagram.com" in u:
            return "https://www.instagram.com/"
        if "pinterest." in u or "pin.it" in u:
            return "https://www.pinterest.com/"
        return "https://www.google.com/"

    def fetch_metadata(self, url):
        if url in self._metadata_loading:
            if url not in self._metadata_cache:
                return
        self._metadata_loading.add(url)
        def worker():
            try:
                cached = self._metadata_cache.get(url)
                info = cached
                if info is None:
                    import yt_dlp
                    ensure_temp_dir()
                    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
                            "socket_timeout": 10, "retries": 0, "extractor_retries": 0,
                            "paths": {"temp": str(TEMP_DIR)}}
                    opts.update(yt_cookie_opts(url, self.cfg))
                    try:
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            info = ydl.extract_info(url, download=False)
                    except Exception as exc:
                        log("metadata yt-dlp %s: %r" % (url, exc))
                        if "cookiesfrombrowser" in opts or "cookiefile" in opts:
                            try:
                                clean_opts = {k: v for k, v in opts.items()
                                             if k not in ("cookiesfrombrowser", "cookiefile")}
                                with yt_dlp.YoutubeDL(clean_opts) as ydl:
                                    info = ydl.extract_info(url, download=False)
                                log("metadata yt-dlp (sin cookies) OK %s" % url)
                            except Exception as exc2:
                                log("metadata yt-dlp sin cookies %s: %r" % (url, exc2))
                                info = None
                    if info is not None:
                        self._metadata_cache[url] = info

                is_yt = ("youtube.com" in (url or "").lower()) or ("youtu.be" in (url or "").lower())
                if info is None and is_yt:
                    info = self._youtube_oembed_info(url)
                    if info is not None:
                        self._metadata_cache[url] = info

                if info is None and ("instagram.com/p/" in (url or "").lower()
                                    or "pinterest." in (url or "").lower()
                                    or "pin.it/" in (url or "").lower()):
                    try:
                        entries = gallery_dl_extract(url, self.cfg)
                        first = entries[0]
                        title = str(first.get("description") or first.get("post_id") or "Publicacion de imagenes")
                        author = str(first.get("username") or first.get("owner") or "Instagram")
                        thumb_data = None
                        thumb_url = (first.get("_indiedl_url") or first.get("_url")
                                     or first.get("url") or first.get("file_url") or first.get("gdl_file_url"))
                        # Solo URLs http(s) descargables: los esquemas internos
                        # (p. ej. ytdl://... de videos) hacen que urlopen falle
                        # con "unknown url type".
                        if thumb_url and not str(thumb_url).lower().startswith(("http://", "https://")):
                            thumb_url = None
                        if thumb_url:
                            try:
                                from urllib.request import Request, urlopen
                                req = Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                                with urlopen(req, timeout=8) as response:
                                    thumb_data = response.read(2500000)
                            except Exception as thumb_exc:
                                log("gallery thumbnail %s: %r" % (url, thumb_exc))
                        meta = "%s  ·  %d imagen(es)  ·  Original" % (author, len(entries))
                        self.after(0, lambda: self.apply_metadata(url, title, meta, thumb_data, "Miniatura cargada" if thumb_data else "No se pudo cargar la miniatura"))
                        return
                    except Exception as gallery_exc:
                        log("metadata gallery-dl %s: %r" % (url, gallery_exc))

                if info is None:
                    self.after(0, lambda: self.apply_metadata(url, "No se pudieron cargar los detalles",
                                                             "El enlace se recibio correctamente. La descarga se puede intentar igualmente; revisa la conexion o el registro.",
                                                             None, "Vista previa no disponible"))
                    return

                title = str(info.get("title") or "Contenido detectado")
                author = str(info.get("uploader") or info.get("channel") or info.get("creator") or "Autor no disponible")
                description = str(info.get("description") or "").strip().replace("\n", " ")
                description = re.sub(r"\s+", " ", description)
                if len(description) > 180:
                    description = description[:177].rstrip() + "…"
                dur = info.get("duration")
                duration = "%d:%02d" % (int(dur)//60, int(dur)%60) if dur else "Duracion no disponible"
                width, height = info.get("width"), info.get("height")
                resolution = "%s x %s" % (width, height) if width and height else "Resolucion disponible al descargar"
                ext = str(info.get("ext") or "media").upper()
                meta = "@%s  ·  %s  ·  %s  ·  %s" % (author.lstrip("@"), duration, resolution, ext)
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
                vid = self._youtube_video_id(url)
                if vid:
                    for suf in ("maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg", "mqdefault.jpg"):
                        thumb_candidates.append("https://i.ytimg.com/vi/%s/%s" % (vid, suf))
                thumb_candidates = list(dict.fromkeys(thumb_candidates))
                referer = self._metadata_referer(url)
                if thumb_candidates:
                    try:
                        from urllib.request import Request, urlopen
                        for thumb_url in thumb_candidates:
                            try:
                                req = Request(thumb_url, headers={
                                    "User-Agent": "Mozilla/5.0",
                                    "Referer": referer,
                                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                })
                                with urlopen(req, timeout=5) as response:
                                    data = response.read(2500000)
                                if data:
                                    thumb_data = data
                                    break
                            except Exception as thumb_exc:
                                log("thumbnail candidate %s (%s): %r" % (url, thumb_url[:100], thumb_exc))
                    except Exception as thumb_exc:
                        log("thumbnail %s: %r" % (url, thumb_exc))
                self.after(0, lambda: self.apply_metadata(url, title, meta, thumb_data, "Miniatura cargada" if thumb_data else "No se pudo cargar la miniatura"))
            except Exception as exc:
                log("fetch_metadata %s: %r\n%s" % (url, exc, traceback.format_exc()))
                self.after(0, lambda: self.apply_metadata(url, "No se pudieron cargar los detalles",
                                                         "El enlace se recibio correctamente. La descarga se puede intentar igualmente; revisa la conexion o el registro.",
                                                         None, "Vista previa no disponible"))
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
                im.thumbnail((300, 169), Image.Resampling.LANCZOS)
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
                _ig_guardar_seguro(txt)
                status.configure(text="Sesión guardada y cifrada (instagram_cookies.bin). "
                                      "Ya no hace falta cerrar el navegador.", text_color=GREEN)
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
        self._sync_mode_controls()

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
            d = os.path.normpath(d)
            self.folder.delete(0, "end")
            self.folder.insert(0, d)
            self._folder_explicit = True
            self._pref_changed("last_dir", d)

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
        folder = self._resolve_folder()
        if folder is None:
            self.msg.configure(text="Descarga cancelada.")
            return
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
        self.cfg["open_folder_done"] = self.v_open.get()
        self.cfg["pcm_resolve"] = self.v_pcm.get()
        self.cfg["usar_parakeet"] = self.v_parakeet.get()
        save_cfg(self.cfg)

        if mode == "image":
            if self._image_selection_ready:
                self._image_selection_ready = False
                self.start_dl(url, mode, folder, quality, clip, self._image_indices)
            else:
                self.begin_image_selection(url, folder, quality)
            return

        self.start_dl(url, mode, folder, quality, clip, None)

    def enter_batch(self, batch):
        self.batch = batch
        self.batch_mode = True
        self._prefix = f"[LOTE {len(batch)}] "
        self.url.configure(state="disabled")
        self.url.delete(0, "end")
        self.url.insert(0, f"Cola de {len(batch)} elementos lista para descargar.")
        self.v_clip.set(False)
        self.clip_frame.grid_remove()
        self.clip_toggle.grid_remove()
        self._sync_mode_controls()

        for widget in self.preview.winfo_children():
            widget.destroy()

        ctk.CTkLabel(self.preview, text="LISTA DE DESCARGA", font=(HEAVY, 16), text_color=YEL).pack(anchor="w", padx=14, pady=(14, 10))

        scroll = SmoothScroll(self.preview, fg_color="#0D1116", registry=self._scroll_areas)
        scroll.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.batch_items_ui = []
        for idx, item in enumerate(batch):
            row = ctk.CTkFrame(scroll.body, fg_color="#151B21", corner_radius=8)
            row.pack(fill="x", pady=4)

            thumb_lbl = ctk.CTkLabel(row, text="…", width=48, height=27, fg_color="#252C33",
                                     text_color=GRAY, corner_radius=4)
            thumb_lbl.pack(side="left", padx=(10, 6), pady=6)

            icon_lbl = ctk.CTkLabel(row, text="⬇", text_color=GRAY, font=(HEAVY, 16), width=30)
            icon_lbl.pack(side="left", padx=(0, 6), pady=10)

            title_text = item.get("title", "Sin título")
            s = item.get("s")
            e = item.get("e")
            if s is not None and e is not None:
                title_text += f"  (✂ {fmt_hms(s)} → {fmt_hms(e)})"
                
            title_lbl = ctk.CTkLabel(row, text=title_text[:60], text_color=WHITE, font=("Segoe UI", 12), anchor="w", justify="left")
            title_lbl.pack(side="left", fill="x", expand=True, pady=10)

            status_lbl = ctk.CTkLabel(row, text="En espera", text_color=GRAY, font=("Segoe UI", 10))
            status_lbl.pack(side="right", padx=10)

            ui_item = {
                "frame": row,
                "icon": icon_lbl,
                "title": title_lbl,
                "status": status_lbl,
                "thumb": thumb_lbl,
                "url": item["url"]
            }
            self.batch_items_ui.append(ui_item)
            self.after(50, lambda it=ui_item, u=item["url"]: self._load_batch_thumb(it, u))

        self.btn.configure(text=f"⬇  DESCARGAR LOTE ({len(batch)})")

    def _load_batch_thumb(self, ui_item, url):
        def worker():
            try:
                target = ui_item["thumb"]
                info = self._metadata_cache.get(url)
                thumb_url = None
                if isinstance(info, dict):
                    thumb_url = info.get("thumbnail")
                    if not thumb_url:
                        thumbs = info.get("thumbnails") or []
                        if thumbs:
                            last = thumbs[-1]
                            thumb_url = last.get("url") if isinstance(last, dict) else (last if isinstance(last, str) else None)
                if not thumb_url:
                    vid = self._youtube_video_id(url) if hasattr(self, "_youtube_video_id") else None
                    if vid:
                        thumb_url = "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid
                if not thumb_url:
                    return
                from urllib.request import Request, urlopen
                import io
                from PIL import Image
                referer = self._metadata_referer(url) if hasattr(self, "_metadata_referer") else "https://www.google.com/"
                req = Request(thumb_url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer,
                                                  "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
                with urlopen(req, timeout=5) as resp:
                    data = resp.read(500000)
                if not data:
                    return
                im = Image.open(io.BytesIO(data)).convert("RGB")
                im.thumbnail((48, 27), Image.Resampling.LANCZOS)
                image = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
                def apply():
                    try:
                        if target.winfo_exists():
                            target.configure(image=image, text="")
                    except Exception:
                        pass
                self.after(0, apply)
                self._batch_thumb_refs = getattr(self, "_batch_thumb_refs", [])
                self._batch_thumb_refs.append(image)
            except Exception as exc:
                try:
                    log("batch thumbnail %s: %r" % (url, exc))
                except Exception:
                    pass
        threading.Thread(target=worker, daemon=True).start()

    def start_batch(self):
        items = self.batch
        folder = self._resolve_folder()
        if folder is None:
            self.msg.configure(text="Descarga cancelada.")
            return
        quality = self.menu.get()
        if not folder:
            self.msg.configure(text="Elegí una carpeta de destino.")
            return

        self.cfg["last_dir"] = folder
        self.cfg["video_q"] = self.menu.get() if self.cur_mode == "video" else self.cfg.get("video_q", "Mejor")
        self.cfg["audio_fmt"] = self.menu.get() if self.cur_mode == "audio" else self.cfg.get("audio_fmt", "mp3")
        self.cfg["ask_folder"] = self.v_ask.get()
        self.cfg["close_when_done"] = self.v_close.get()
        self.cfg["open_folder_done"] = self.v_open.get()
        self.cfg["pcm_resolve"] = self.v_pcm.get()
        self.cfg["usar_parakeet"] = self.v_parakeet.get()
        save_cfg(self.cfg)

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
        self._last_warn = ""

        def worker():
            success = 0
            total = len(items)
            for idx, item in enumerate(items):
                if self.cancel.is_set():
                    break
                u = item["url"]
                title = item.get("title", "")
                s = item.get("s")
                e = item.get("e")
                section = (s, e) if s is not None and e is not None else None

                self.q.put(("batch_ui", idx, "downloading", "Descargando..."))
                self.q.put(("log", f"[{idx+1}/{total}] Iniciando: {title or u}"))

                try:
                    run_download(u, self.cur_mode, folder, self.cfg, self.q, quality, self.cancel, section=section, is_batch=True)
                    success += 1
                    self.q.put(("batch_ui", idx, "done", "Completado"))
                except Exception as e:
                    short = str(e).split(".")[0][:60] or "Error"
                    self.q.put(("batch_ui", idx, "error", short))
                    self.q.put(("log", f"Error en {title or u}: {e}"))

                if idx < total - 1 and not self.cancel.is_set():
                    self.q.put(("log", "Esperando 3 segundos para evitar detección de bots..."))
                    time.sleep(3)

            if self.cancel.is_set():
                self.q.put(("err", "Cancelado"))
            else:
                self.q.put(("done", folder, f"Lote finalizado: {success}/{total} completados."))

        threading.Thread(target=worker, daemon=True).start()

    def start_dl(self, url, mode, folder, quality, clip, image_indices):
        # Instagram (video/audio): si todavía no hay sesión guardada, se busca
        # en los navegadores primero (una sola vez por corrida). Así no hace
        # falta importar nada a mano ni volver a procesar.
        if ("instagram.com" in (url or "").lower()
                and not getattr(self, "_ig_auto_dl_done", False)
                and not cookies_file_path(self.cfg)):
            self._ig_auto_dl_done = True
            self.msg.configure(text="Buscando tu sesión de Instagram en los navegadores…")
            def _continuar(ok, *a):
                if not ok:
                    self.msg.configure(text="No encontré sesión de Instagram; intento sin sesión.")
                self.start_dl(url, mode, folder, quality, clip, image_indices)
            self.auto_detect_session(_continuar)
            return
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
        self._finish_seq = getattr(self, "_finish_seq", 0) + 1
        job = getattr(self, "_close_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            self._close_job = None
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
                if not self.busy and kind in ("stage", "prog", "log", "note", "warn", "batch_ui"):
                    # Eventos tardíos de una descarga ya cerrada: no tocar la UI.
                    continue
                if kind == "stage":
                    _, idx, text = ev
                    self.set_stage(idx, text)
                elif kind == "batch_ui":
                    _, idx, state, text = ev
                    if hasattr(self, "batch_items_ui") and idx < len(self.batch_items_ui):
                        item_ui = self.batch_items_ui[idx]
                        if state == "downloading":
                            item_ui["icon"].configure(text="⏳", text_color=YEL)
                            item_ui["status"].configure(text=text, text_color=YEL)
                        elif state == "done":
                            item_ui["icon"].configure(text="✓", text_color=GREEN)
                            item_ui["status"].configure(text=text, text_color=GREEN)
                        elif state == "error":
                            item_ui["icon"].configure(text="✕", text_color=RED)
                            item_ui["status"].configure(text=text, text_color=RED)
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
        self._finish_seq = getattr(self, "_finish_seq", 0) + 1
        seq = self._finish_seq

        # 1) Cortar ya cualquier barra animada: nunca se superpone al estado final.
        for row in self.rows:
            self._cancel_bar_anim(row["bar"])
            self._hide_row_bar(row)
            row["pc"].configure(text="")
        self._set_rbar(1.0)
        self.p_top.configure(text=f"{self._prefix}FINALIZANDO")
        self.p_title.configure(text="Finalizando…")
        self._set_status("●  FINALIZANDO", YEL)

        # 2) Completar los pasos en cascada, sin tocar las barras.
        for i, row in enumerate(self.rows):
            self.after(60 * i, lambda r=row, s=seq: self._mark_step_done(r, s))

        warn_text = getattr(self, "_last_warn", "")
        self._last_warn = ""

        hist = self.cfg.get("history", [])
        if getattr(self, "batch_mode", False) and self.batch:
            site = site_name(self.batch[0].get("url", ""))
        else:
            site = site_name(self.url.get())
        item = {"title": title, "site": site, "when": time.strftime("%d/%m/%Y %H:%M"),
                "mode": self.cur_mode, "folder": folder}
        hist.insert(0, item)
        self.cfg["history"] = hist[:50]
        self.cfg["last_saved"] = folder
        save_cfg(self.cfg)
        self.prepend_hist(item)

        # 3) Recién cuando los pasos terminaron se muestra el estado final.
        delay = 60 * max(0, len(self.rows) - 1) + 160
        self.after(delay, lambda: self._show_completion(seq, warn_text, folder))

    def _mark_step_done(self, row, seq):
        if getattr(self, "_finish_seq", 0) != seq:
            return
        try:
            row["ic"].configure(fg_color=YEL, border_width=0)
            row["il"].configure(text="✓", text_color=BLACK, font=(HEAVY, 14))
            row["tx"].configure(text=row["name"], text_color=WHITE,
                                font=("Segoe UI Semibold", 15))
        except Exception:
            pass

    def _show_completion(self, seq, warn_text, folder=""):
        if getattr(self, "_finish_seq", 0) != seq:
            return
        self.b_open.configure(state="normal")
        self.show_buttons("done")
        self.btn.configure(state="normal", text="⬇  DESCARGAR")
        if warn_text:
            self.p_top.configure(text=f"{self._prefix}COMPLETADO CON AVISOS")
            self.p_title.configure(text="Descargado con avisos")
            self.p_msg.configure(text=warn_text, text_color=YEL)
            self._set_status("●  AVISO", YEL)
        else:
            self.p_top.configure(text=f"{self._prefix}COMPLETADO")
            self.p_title.configure(text="¡Completado!")
            self.p_msg.configure(text="", text_color=RED)
            self._set_status("●  COMPLETADO", GREEN)
        if folder and self.cfg.get("open_folder_done"):
            self.after(350, lambda: self.open_dir(folder))
        if self.cfg.get("close_when_done"):
            self._close_job = self.after(1800, self._on_close)

    def finish_error(self, err):
        self.busy = False
        self._finish_seq = getattr(self, "_finish_seq", 0) + 1
        for row in self.rows:
            self._cancel_bar_anim(row["bar"])
        self.show_buttons("done")
        self.btn.configure(state="normal", text="⬇  DESCARGAR")
        cancelled = "cancelado" in str(err).lower()
        self.p_msg.configure(text="" if cancelled else err, text_color=RED)
        # Actualizar estado de los items de la cola (no dejar "Descargando")
        if getattr(self, "batch_mode", False) and hasattr(self, "batch_items_ui"):
            for ui in self.batch_items_ui:
                try:
                    st = ui["status"]
                    txt = st.cget("text")
                    if txt not in ("Completado",):
                        st.configure(text="Cancelado" if cancelled else "Error", text_color=GRAY if cancelled else RED)
                        ui["icon"].configure(text="■" if cancelled else "✕", text_color=GRAY if cancelled else RED)
                except Exception:
                    pass
        if 0 <= self.stage < len(self.rows):
            self.rows[self.stage]["ic"].configure(fg_color="#DDD" if cancelled else RED, border_width=0)
            self.rows[self.stage]["il"].configure(text="■" if cancelled else "✕",
                                                  text_color=BLACK if cancelled else WHITE)
            self._hide_row_bar(self.rows[self.stage])
        self.p_title.configure(text="Cancelado" if cancelled else "Error")
        self.p_top.configure(text=f"{self._prefix}{'CANCELADO' if cancelled else 'ERROR'}")
        self._set_status("●  CANCELADO" if cancelled else "●  ERROR", GRAY if cancelled else RED)
        self._set_rbar(0.0)



def build_app():
    ctk.set_appearance_mode("dark")
    uri = sys.argv[1] if len(sys.argv) > 1 else ""

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

    App(mode, url, batch, clip).mainloop()