"""
canopy.ui.main_window — CanopyApp: main window, layout, and all widget logic.

This module owns the tkinter/CTk widget tree, the thread-safe UI queue,
logging helpers, history rendering, and the WKWebView lifecycle.
Download logic lives in canopy.core.downloader.
History persistence lives in canopy.core.history.
Browser constants and JS live in canopy.core.browser.
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import threading
import queue
import subprocess
import os
import sys
import datetime
import urllib.request
import webbrowser

try:
    from PIL import Image
    _PILLOW = True
except ImportError:
    _PILLOW = False

# ── Canopy module imports ────────────────────────────────────────────────────

from canopy.ui.theme import (
    BG, TITLEBAR, CARD, BORDER, ACCENT, FG, MUTED, DIM,
    PILL_BG, PILL_FG, LOG_BG, LOG_GRN, LOG_MUT, LOG_DIM, PROG_TRK,
    FONT_MONO, THUMB_W, THUMB_H, HIST_TW, HIST_TH,
)
from canopy.ui.browser_panel import BrowserPanel
from canopy.ui.picker_dialog import show_picker
import canopy.core.history as history
from canopy.core.downloader import Downloader, FFMPEG_PATH
from canopy.core.browser import (
    HAS_WKWEBVIEW, WEBVIEW_JS, _ALLOWED_PREFIXES,
)
from version import VERSION


# ── Asset helpers ────────────────────────────────────────────────────────────

def _assets_path(filename: str) -> str:
    """Resolve a file inside assets/ for both dev and PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        # This file lives at canopy/ui/main_window.py; project root is 2 up.
        base = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    return os.path.join(base, "assets", filename)


def _load_brand_mark(size: int = 32):
    """Load canopy-green-512.png and return a CTkImage at *size* logical pt."""
    if not _PILLOW:
        return None
    path = _assets_path("canopy-green-512.png")
    if not os.path.exists(path):
        return None
    try:
        src = Image.open(path).convert("RGBA")
        return ctk.CTkImage(light_image=src, size=(size, size))
    except Exception:
        return None


def _set_dock_icon() -> None:
    """Set the macOS dock icon at runtime using the 512 px icon PNG."""
    if not _PILLOW:
        return
    path = _assets_path("canopy-icon-512.png")
    if not os.path.exists(path):
        return
    try:
        from AppKit import NSApplication, NSImage
        ns_img = NSImage.alloc().initWithContentsOfFile_(path)
        if ns_img:
            NSApplication.sharedApplication().setApplicationIconImage_(ns_img)
    except Exception:
        pass


# ── CanopyApp ────────────────────────────────────────────────────────────────

class CanopyApp:

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root

        # Thread-safe UI queue — background threads push callables here;
        # only the main thread drains it, avoiding PyEval_RestoreThread crashes.
        self._ui_q = queue.Queue()
        self._poll_ui_q()

        self.root.title(f"Canopy")
        self.root.geometry("580x860")
        self.root.minsize(580, 600)
        self.root.resizable(False, True)
        self.root.configure(fg_color=BG)

        # ── State ──────────────────────────────────────────────────────────
        self.download_path         = os.path.expanduser("~/Downloads")
        self._current_url          = ""
        self._current_fmt          = "mp4"
        self._current_quality      = "Best"
        self.info                  = None
        self.is_fetching           = False
        self.is_downloading        = False
        self.activity_open         = True
        self._thumb_refs: dict     = {}
        self._dl_log_handle        = None
        self._dl_log_path          = None
        self._last_log_replaceable = False
        self._download_completed   = False
        self._history_rows: list   = []
        self._last_filename        = None

        # ── Browser state ──────────────────────────────────────────────────
        self._wkwebview         = None
        self._wv_nswin          = None
        self._browser_panel     = None
        self._browser_panel_obj = None   # BrowserPanel instance
        self._browser_url_entry = None
        self._browser_url_var   = None
        self._browser_visible   = False
        self._wv_poll_count     = 0
        self._wv_last_url       = ""
        self._pre_browser_w     = 580
        self._browser_nav_h     = 0

        # ── Tk vars ────────────────────────────────────────────────────────
        self.format_var  = tk.StringVar(value="MP4")
        self.quality_var = tk.StringVar(value="Best")
        self._opt_show_in_folder = tk.BooleanVar(value=False)
        self._opt_open_when_done = tk.BooleanVar(value=False)

        # ── Downloader ─────────────────────────────────────────────────────
        self._downloader = Downloader(
            ui_dispatch       = self._ui,
            write_log         = self._write_log,
            on_fetch_done     = self._on_fetch_done,
            on_progress       = self._set_progress,
            on_download_done  = self._on_download_done,
            on_download_error = self._on_download_error,
            on_log_update     = self._log_update,
        )

        # ── Bootstrap ──────────────────────────────────────────────────────
        self.history = history.load()
        os.makedirs(history.THUMB_CACHE, exist_ok=True)
        os.makedirs(history.DL_LOGS_DIR, exist_ok=True)
        self._setup_log()
        _set_dock_icon()
        self._build_ui()
        self._refresh_history()

    # ── Thread-safe UI dispatch ───────────────────────────────────────────────

    def _ui(self, fn) -> None:
        """Schedule fn() on the main thread (safe to call from any thread)."""
        self._ui_q.put(fn)

    def _poll_ui_q(self) -> None:
        """Drain the UI queue — runs only on the main thread (~60 fps)."""
        try:
            while True:
                fn = self._ui_q.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.root.after(16, self._poll_ui_q)

    # ── Logging ───────────────────────────────────────────────────────────────

    def _setup_log(self) -> None:
        try:
            if os.path.getsize(history.LOG_FILE) > 5 * 1024 * 1024:
                open(history.LOG_FILE, "w").close()
        except OSError:
            pass
        self._log_file = open(history.LOG_FILE, "a",
                               buffering=1, encoding="utf-8")
        self._write_log("=" * 60)
        self._write_log(
            f"Canopy {VERSION} session started  ffmpeg={FFMPEG_PATH or 'NOT FOUND'}"
        )

    def _write_log(self, msg: str) -> None:
        ts   = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        try:
            self._log_file.write(line)
        except Exception:
            pass
        if self._dl_log_handle:
            try:
                self._dl_log_handle.write(line)
            except Exception:
                pass

    def _open_dl_log(self, video_id: str, title: str) -> str | None:
        self._close_dl_log()
        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{ts}_{video_id}.txt"
        path  = os.path.join(history.DL_LOGS_DIR, fname)
        try:
            self._dl_log_handle = open(path, "w", buffering=1, encoding="utf-8")
            self._dl_log_path   = path
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._dl_log_handle.write(
                f"Canopy — Process Log\n{'=' * 50}\n"
                f"Date:    {now}\nVideo:   {title}\nID:      {video_id}\n"
                f"ffmpeg:  {FFMPEG_PATH or 'NOT FOUND'}\n{'=' * 50}\n\n"
            )
        except Exception:
            self._dl_log_handle = None
            self._dl_log_path   = None
        return self._dl_log_path

    def _close_dl_log(self) -> None:
        if self._dl_log_handle:
            try:
                self._dl_log_handle.write("\n[END OF LOG]\n")
                self._dl_log_handle.close()
            except Exception:
                pass
            self._dl_log_handle = None

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        PAD = 22

        # ── Title bar ─────────────────────────────────────────────────────
        tbar = ctk.CTkFrame(self.root, fg_color=TITLEBAR,
                             corner_radius=0, height=44)
        tbar.pack(fill="x")
        tbar.pack_propagate(False)

        self.paste_btn = ctk.CTkButton(
            tbar, text="⎘  Paste Link",
            font=("Helvetica", 13, "bold"),
            fg_color=ACCENT, hover_color="#3d6b4a", text_color="#ffffff",
            corner_radius=20, width=128, height=30,
            command=self._paste_link,
        )
        self.paste_btn.place(relx=0.0, rely=0.5, anchor="w", x=PAD)

        brand_frame = ctk.CTkFrame(tbar, fg_color="transparent", corner_radius=0)
        brand_frame.place(relx=0.5, rely=0.5, anchor="center")

        brand_img = _load_brand_mark(32)
        if brand_img:
            ctk.CTkLabel(brand_frame, image=brand_img, text="",
                         fg_color="transparent").pack(side="left")
            self._brand_img_ref = brand_img

        ctk.CTkLabel(brand_frame,
                     text="C A N O P Y",
                     font=("Helvetica Neue", 12),
                     text_color="#2a2520",
                     fg_color="transparent").pack(side="left", padx=(7, 0))

        hist_lnk = ctk.CTkLabel(tbar, text="History",
                                  font=("Helvetica", 12, "bold"),
                                  text_color=ACCENT,
                                  fg_color="transparent",
                                  cursor="hand2")
        hist_lnk.place(relx=1.0, rely=0.5, anchor="e", x=-PAD)
        hist_lnk.bind("<Button-1>",
                      lambda e: self.hist_scroll._parent_canvas.yview_moveto(1.0))

        about_lnk = ctk.CTkLabel(tbar, text="About",
                                   font=("Helvetica", 12),
                                   text_color=MUTED,
                                   fg_color="transparent",
                                   cursor="hand2")
        about_lnk.place(relx=1.0, rely=0.5, anchor="e", x=-PAD - 68)
        about_lnk.bind("<Button-1>", lambda e: self._show_about())

        ctk.CTkFrame(self.root, fg_color=BORDER,
                     height=1, corner_radius=0).pack(fill="x")

        # ── Browser bar ────────────────────────────────────────────────────
        bb_row = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        bb_row.pack(fill="x", padx=PAD, pady=(10, 0))

        bb_pill = ctk.CTkFrame(bb_row, fg_color=CARD, corner_radius=10,
                                border_color=BORDER, border_width=1,
                                cursor="hand2")
        bb_pill.pack(fill="x")

        bb_inner = ctk.CTkFrame(bb_pill, fg_color="transparent", corner_radius=0)
        bb_inner.pack(fill="x", padx=12, pady=9)

        ctk.CTkLabel(bb_inner, text="🌐",
                     font=("Helvetica", 14), text_color=MUTED,
                     fg_color="transparent",
                     cursor="hand2").pack(side="left", padx=(0, 8))

        ctk.CTkLabel(bb_inner, text="Click to open browser",
                     font=("Helvetica", 13), text_color=MUTED,
                     fg_color="transparent", anchor="w",
                     cursor="hand2").pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(bb_inner, text="Open ↗",
                     font=("Helvetica", 11, "bold"), text_color=ACCENT,
                     fg_color="transparent",
                     cursor="hand2").pack(side="right")

        def _bb_open(e=None):
            self._open_browser()

        for _w in [bb_pill, bb_inner] + list(bb_inner.winfo_children()):
            _w.bind("<Button-1>", _bb_open)

        # ── Body ───────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        body.pack(fill="x")

        inner = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        inner.pack(fill="x", padx=PAD, pady=(14, 0))

        # Video info card
        self.video_card = ctk.CTkFrame(inner, fg_color=CARD,
                                        corner_radius=14,
                                        border_color=BORDER, border_width=1)
        self.video_card.pack(fill="x", pady=(0, 10))

        self.vc_thumb_box = ctk.CTkFrame(self.video_card, fg_color="#c8e6d4",
                                          corner_radius=0, height=THUMB_H)
        self.vc_thumb_box.pack(fill="x")
        self.vc_thumb_box.pack_propagate(False)

        self.vc_thumb_lbl = ctk.CTkLabel(self.vc_thumb_box, text="▶",
                                          font=("Helvetica", 36),
                                          text_color=ACCENT,
                                          fg_color="transparent")
        self.vc_thumb_lbl.pack(expand=True)
        self._vc_photo = None

        vc_info = ctk.CTkFrame(self.video_card, fg_color=CARD, corner_radius=0)
        vc_info.pack(fill="x", padx=16, pady=(12, 14))

        self.vc_title = ctk.CTkLabel(vc_info,
                                      text="Paste a YouTube URL to get started",
                                      font=("Helvetica", 15, "bold"),
                                      text_color=MUTED,
                                      fg_color="transparent",
                                      anchor="w", justify="left",
                                      wraplength=500)
        self.vc_title.pack(fill="x")

        self.vc_meta = ctk.CTkLabel(vc_info, text="",
                                     font=("Helvetica", 12),
                                     text_color=MUTED,
                                     fg_color="transparent",
                                     anchor="w")
        self.vc_meta.pack(fill="x", pady=(5, 0))

        pill_row = ctk.CTkFrame(vc_info, fg_color=CARD, corner_radius=0)
        pill_row.pack(fill="x", pady=(10, 0))

        self.vc_fmt_pill = ctk.CTkLabel(pill_row, text="MP4",
                                         font=("Helvetica", 10, "bold"),
                                         fg_color=PILL_BG,
                                         text_color=PILL_FG,
                                         corner_radius=10,
                                         padx=8, pady=2)
        self.vc_fmt_pill.pack(side="left")

        self.vc_qual_pill = ctk.CTkLabel(pill_row, text="Best",
                                          font=("Helvetica", 10, "bold"),
                                          fg_color="#e8ede6",
                                          text_color="#5a7060",
                                          corner_radius=10,
                                          padx=8, pady=2)
        self.vc_qual_pill.pack(side="left", padx=(6, 0))

        # Options row
        opts_row = ctk.CTkFrame(inner, fg_color=BG, corner_radius=0)
        opts_row.pack(fill="x", pady=(0, 10))

        self._opt_fmt = self._option_card(opts_row, "FORMAT", self.format_var,
                                          ["MP4", "MP3", "M4A", "WEBM"])
        self._opt_fmt.pack(side="left", fill="x", expand=True)

        ctk.CTkFrame(opts_row, fg_color=BG, width=8,
                     corner_radius=0).pack(side="left")

        self._opt_qual = self._option_card(opts_row, "QUALITY", self.quality_var,
                                           ["Best", "4K", "1080p", "720p", "480p", "360p"])
        self._opt_qual.pack(side="left", fill="x", expand=True)

        ctk.CTkFrame(opts_row, fg_color=BG, width=8,
                     corner_radius=0).pack(side="left")

        save_card = ctk.CTkFrame(opts_row, fg_color=CARD,
                                  corner_radius=14,
                                  border_color=BORDER, border_width=1,
                                  cursor="hand2")
        save_card.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(save_card, text="SAVE TO",
                     font=("Helvetica", 9, "bold"),
                     text_color=MUTED,
                     fg_color="transparent",
                     anchor="w").pack(anchor="w", padx=12, pady=(10, 0))

        save_val = ctk.CTkFrame(save_card, fg_color=CARD, corner_radius=0)
        save_val.pack(fill="x", padx=12, pady=(2, 10))

        self.folder_label = ctk.CTkLabel(save_val,
                                          text=self._short_path(self.download_path),
                                          font=("Helvetica", 12, "bold"),
                                          text_color=ACCENT,
                                          fg_color="transparent",
                                          anchor="w")
        self.folder_label.pack(side="left")

        ctk.CTkLabel(save_val, text="▾",
                     font=("Helvetica", 10),
                     text_color=DIM,
                     fg_color="transparent").pack(side="left", padx=(4, 0))

        def _pick_click(e=None):
            self._pick_folder()

        def _bind_tree(widget):
            widget.bind("<Button-1>", _pick_click)
            for child in widget.winfo_children():
                _bind_tree(child)

        _bind_tree(save_card)

        self.format_var.trace_add("write",  lambda *_: self._sync_pills())
        self.quality_var.trace_add("write", lambda *_: self._sync_pills())

        # Progress card
        self._build_progress_card(inner)

        ctk.CTkFrame(self.root, fg_color=BORDER,
                     height=1, corner_radius=0).pack(fill="x")

        # Sticky download footer
        self._build_dl_footer(PAD)

        self._build_history_section(PAD)

    # ── Sticky download footer ────────────────────────────────────────────────
    # IMPORTANT: dl_btn is placed with place() at y = window_height - 74.
    # Do NOT convert this to pack() or grid().

    _DL_FOOTER_H  = 74
    _dl_footer_on = False

    def _build_dl_footer(self, pad: int) -> None:
        self._dl_pad    = pad
        self._dl_footer = tk.Frame(self.root, bg=BG)
        tk.Frame(self._dl_footer, bg=BORDER, height=1).pack(fill="x")

        self.dl_btn = ctk.CTkButton(
            self._dl_footer, text="Download",
            font=("Helvetica", 15, "bold"),
            fg_color=ACCENT, hover_color="#3d6b4a", text_color="#ffffff",
            corner_radius=14, height=50,
            state="disabled", command=self._start_download,
        )
        self.dl_btn.pack(fill="x", padx=pad, pady=12)
        self.root.bind("<Configure>", self._dl_footer_reposition, add="+")

    def _dl_footer_reposition(self, _e=None) -> None:
        if not self._dl_footer_on:
            return
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        self._dl_footer.place(x=0, y=h - self._DL_FOOTER_H,
                               width=w, height=self._DL_FOOTER_H)
        self._dl_footer.lift()

    def _show_dl_footer(self) -> None:
        self._dl_footer_on = True
        self._dl_footer_reposition()

    def _hide_dl_footer(self) -> None:
        self._dl_footer_on = False
        self._dl_footer.place_forget()

    # ── Option cards (FORMAT / QUALITY) ──────────────────────────────────────

    def _option_card(self, parent, label: str, var, choices: list):
        card = ctk.CTkFrame(parent, fg_color=CARD,
                             corner_radius=14,
                             border_color=BORDER, border_width=1,
                             cursor="hand2")

        ctk.CTkLabel(card, text=label,
                     font=("Helvetica", 9, "bold"),
                     text_color=MUTED,
                     fg_color="transparent",
                     anchor="w").pack(anchor="w", padx=12, pady=(10, 0))

        val_row = ctk.CTkFrame(card, fg_color=CARD, corner_radius=0)
        val_row.pack(fill="x", padx=12, pady=(2, 10))

        val_lbl = ctk.CTkLabel(val_row, textvariable=var,
                                font=("Helvetica", 14, "bold"),
                                text_color=FG,
                                fg_color="transparent",
                                anchor="w")
        val_lbl.pack(side="left")

        ctk.CTkLabel(val_row, text="▾",
                     font=("Helvetica", 10),
                     text_color=DIM,
                     fg_color="transparent").pack(side="left", padx=(4, 0))

        def show_menu(e=None):
            m = tk.Menu(card, tearoff=0, font=("Helvetica", 12),
                        bg=CARD, fg=FG,
                        activebackground=ACCENT, activeforeground="#fff")
            for c in choices:
                m.add_command(label=c, command=lambda v=c: var.set(v))
            try:
                m.tk_popup(card.winfo_rootx(),
                           card.winfo_rooty() + card.winfo_height())
            finally:
                m.grab_release()

        card.bind("<Button-1>", show_menu)
        val_row.bind("<Button-1>", show_menu)
        val_lbl.bind("<Button-1>", show_menu)
        return card

    def _sync_pills(self) -> None:
        self.vc_fmt_pill.configure(text=self.format_var.get().upper())
        self.vc_qual_pill.configure(text=self.quality_var.get())

    # ── Progress card ─────────────────────────────────────────────────────────

    def _build_progress_card(self, parent) -> None:
        self.prog_card = ctk.CTkFrame(parent, fg_color=CARD,
                                       corner_radius=14,
                                       border_color=BORDER, border_width=1)
        self.prog_card.pack(fill="x", pady=(0, 10))

        pc = ctk.CTkFrame(self.prog_card, fg_color=CARD, corner_radius=0)
        pc.pack(fill="x", padx=16, pady=(14, 10))

        status_row = ctk.CTkFrame(pc, fg_color=CARD, corner_radius=0)
        status_row.pack(fill="x")

        self.prog_status = ctk.CTkLabel(status_row, text="Ready",
                                         font=("Helvetica", 14, "bold"),
                                         text_color=ACCENT,
                                         fg_color="transparent",
                                         anchor="w")
        self.prog_status.pack(side="left")

        self.prog_pct = ctk.CTkLabel(status_row, text="",
                                      font=("Helvetica", 22, "bold"),
                                      text_color=ACCENT,
                                      fg_color="transparent",
                                      anchor="e")
        self.prog_pct.pack(side="right")

        self.act_bar = ctk.CTkProgressBar(pc,
                                           fg_color=PROG_TRK,
                                           progress_color=ACCENT,
                                           corner_radius=99,
                                           height=8)
        self.act_bar.set(0)
        self.act_bar.pack(fill="x", pady=(10, 0))

        self.prog_detail = ctk.CTkLabel(pc, text="",
                                         font=("Helvetica", 12),
                                         text_color=MUTED,
                                         fg_color="transparent",
                                         anchor="w")
        self.prog_detail.pack(fill="x", pady=(8, 0))

        tog_row = ctk.CTkFrame(pc, fg_color=CARD, corner_radius=0,
                                cursor="hand2")
        tog_row.pack(fill="x", pady=(8, 0))

        self.log_chevron = ctk.CTkLabel(tog_row, text="▾",
                                         font=("Helvetica", 10),
                                         text_color=DIM,
                                         fg_color="transparent",
                                         cursor="hand2")
        self.log_chevron.pack(side="left")

        ctk.CTkLabel(tog_row, text="  Activity log",
                     font=("Helvetica", 10),
                     text_color=MUTED,
                     fg_color="transparent",
                     cursor="hand2").pack(side="left")

        tog_row.bind("<Button-1>", lambda e: self._toggle_activity())
        for w in tog_row.winfo_children():
            w.bind("<Button-1>", lambda e: self._toggle_activity())

        self.log_body = ctk.CTkFrame(pc, fg_color=CARD, corner_radius=0)
        self.log_body.pack(fill="x", pady=(6, 0))

        log_bg = ctk.CTkFrame(self.log_body, fg_color=LOG_BG, corner_radius=10)
        log_bg.pack(fill="x")

        self._log_text = tk.Text(log_bg, bg=LOG_BG, fg=LOG_MUT,
                                  font=FONT_MONO, height=6,
                                  relief="flat", bd=0,
                                  state="disabled", wrap="char",
                                  padx=12, pady=10,
                                  highlightthickness=0,
                                  insertbackground=LOG_GRN,
                                  selectbackground=ACCENT)
        self._log_text.pack(fill="x")
        self._log_text.tag_config("ts",      foreground="#5a5a50")
        self._log_text.tag_config("green",   foreground=LOG_GRN)
        self._log_text.tag_config("muted",   foreground=LOG_MUT)
        self._log_text.tag_config("dim",     foreground=LOG_DIM)
        self._log_text.tag_config("active",  foreground=LOG_GRN)
        self._log_text.tag_config("success", foreground=LOG_GRN)
        self._log_text.tag_config("error",   foreground="#ff6b6b")
        self._log_text.tag_config("warn",    foreground="#f5a623")

        self._log("Waiting for a URL...", "dim")

    # ── History section ───────────────────────────────────────────────────────

    def _build_history_section(self, PAD: int) -> None:
        hist_hdr = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        hist_hdr.pack(fill="x", padx=PAD, pady=(16, 10))

        ctk.CTkLabel(hist_hdr, text="Recent Downloads",
                     font=("Helvetica", 16, "bold"),
                     text_color=FG,
                     fg_color="transparent").pack(side="left")

        self.hist_count = ctk.CTkLabel(hist_hdr, text="",
                                        font=("Helvetica", 10),
                                        text_color=MUTED,
                                        fg_color="transparent")
        self.hist_count.pack(side="left", padx=(8, 0))

        self.hist_scroll = ctk.CTkScrollableFrame(
            self.root,
            fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED,
            corner_radius=0,
        )
        self.hist_scroll.pack(fill="both", expand=True, padx=PAD, pady=(0, 24))

        self._build_browser_panel()

    # ── Activity log helpers ──────────────────────────────────────────────────

    def _log(self, text: str, kind: str = "muted") -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_text.config(state="normal")
        self._log_text.insert("end", f"{ts}  ", "ts")
        self._log_text.insert("end", f"{text}\n", kind)
        self._log_text.config(state="disabled")
        self._log_text.see("end")
        self._last_log_replaceable = False

    def _log_update(self, text: str, kind: str = "active") -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_text.config(state="normal")
        if self._last_log_replaceable:
            self._log_text.delete("end-2l linestart", "end-1l linestart")
        self._log_text.insert("end", f"{ts}  {text}\n", kind)
        self._log_text.config(state="disabled")
        self._log_text.see("end")
        self._last_log_replaceable = True

    def _log_clear(self) -> None:
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")
        self._last_log_replaceable = False

    def _pill(self, text: str, bg=None, fg=None) -> None:
        color_map = {
            "Idle":        MUTED,
            "Fetching":    ACCENT,
            "Ready":       ACCENT,
            "Downloading": ACCENT,
            "Done":        ACCENT,
            "Error":       "#cc3333",
        }
        self.prog_status.configure(text=text,
                                   text_color=color_map.get(text, MUTED))

    def _toggle_activity(self) -> None:
        self.activity_open = not self.activity_open
        if self.activity_open:
            self.log_body.pack(fill="x", pady=(6, 0))
            self.log_chevron.configure(text="▾")
        else:
            self.log_body.pack_forget()
            self.log_chevron.configure(text="▸")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.download_path)
        if folder:
            self.download_path = folder
            self.folder_label.configure(text=self._short_path(folder))

    def _paste_link(self) -> None:
        try:
            url = self.root.clipboard_get().strip()
        except Exception:
            url = ""
        if not url:
            messagebox.showinfo("Nothing to paste",
                                "Copy a YouTube URL first, then click Paste Link.")
            return
        self._current_url = url
        self._fetch_info()

    def _fetch_info(self) -> None:
        url = self._current_url
        if not url or self.is_fetching or self.is_downloading:
            return
        self.is_fetching = True
        self.paste_btn.configure(state="disabled")
        self.dl_btn.configure(state="disabled")
        self.vc_title.configure(text="Fetching video info...", text_color=MUTED)
        self.vc_meta.configure(text="")
        self._log_clear()
        self._log(f"Fetching: {url[:60]}", "green")
        self._pill("Fetching")
        self.act_bar.set(0)
        self.prog_detail.configure(text="")
        self.prog_pct.configure(text="")
        self._downloader.fetch(url)

    def _on_fetch_done(self, title: str, meta: str,
                        thumb_url: str, video_id: str,
                        info: dict | None, success: bool) -> None:
        self.is_fetching = False
        self.paste_btn.configure(state="normal")
        if success:
            self.info = info          # store info dict for download use
            self.vc_title.configure(text=title, text_color=FG)
            self.vc_meta.configure(text=meta)
            self.dl_btn.configure(state="normal")
            self._show_dl_footer()
            self._log(f"Found: {title[:55]}", "muted")
            if meta:
                self._log(meta, "dim")
            self._pill("Ready")
            if thumb_url and video_id:
                threading.Thread(target=self._load_vc_thumb,
                                 args=(thumb_url, video_id),
                                 daemon=True).start()
        else:
            self.vc_title.configure(text="Could not fetch video info",
                                    text_color="#cc3333")
            self._log(f"Error: {title[:80]}", "error")
            self._pill("Error")

    def _load_vc_thumb(self, thumb_url: str, video_id: str) -> None:
        cached = os.path.join(history.THUMB_CACHE, f"{video_id}.jpg")
        if not os.path.exists(cached):
            try:
                req = urllib.request.Request(
                    thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    with open(cached, "wb") as f:
                        f.write(r.read())
            except Exception:
                return
        if _PILLOW and os.path.exists(cached):
            try:
                img   = Image.open(cached).convert("RGB")
                iw, ih = img.size
                scale  = THUMB_W / iw
                new_w, new_h = THUMB_W, max(THUMB_H, int(ih * scale))
                img = img.resize((new_w, new_h), Image.LANCZOS)
                if new_h > THUMB_H:
                    top = (new_h - THUMB_H) // 2
                    img = img.crop((0, top, THUMB_W, top + THUMB_H))
                ctk_img = ctk.CTkImage(light_image=img, size=(THUMB_W, THUMB_H))
                def _apply(ci=ctk_img):
                    self._vc_photo = ci
                    self.vc_thumb_lbl.configure(image=ci, text="")
                    self.vc_thumb_box.configure(fg_color="#1c1c1e")
                self._ui(_apply)
            except Exception:
                pass

    def _start_download(self) -> None:
        if not self.info:
            return
        if self.is_downloading:
            messagebox.showwarning("Download In Progress",
                                   "A download is already running. Please wait.")
            return
        show_picker(
            self.root, self.info, history.THUMB_CACHE,
            self._opt_show_in_folder, self._opt_open_when_done,
            on_pick=self._begin_download,
        )

    def _begin_download(self, fmt: str, quality: str) -> None:
        if not self.info or self.is_downloading:
            return
        url      = self._current_url
        title    = self.info.get("title", "Unknown")
        video_id = self.info.get("id", "unknown")
        self.is_downloading      = True
        self._download_completed = False
        self._current_fmt        = fmt
        self._current_quality    = quality
        self.format_var.set(fmt.upper())
        self.quality_var.set(quality)
        self._open_dl_log(video_id, title)
        self._hide_dl_footer()
        self.dl_btn.configure(state="disabled")
        self.paste_btn.configure(state="disabled")
        self.act_bar.set(0)
        self.prog_detail.configure(text="")
        self.prog_pct.configure(text="")
        self._log(f"Starting {fmt.upper()} {quality} download...", "green")
        self._pill("Downloading")
        self._downloader.download(url, fmt, quality, self.download_path)

    def _set_progress(self, pct: float, detail: str,
                       pct_str: str | None = None) -> None:
        self.act_bar.set(pct / 100)
        self.prog_detail.configure(text=detail)
        if pct_str is not None:
            self.prog_pct.configure(text=pct_str)
        self._log_update(f"Downloading  {detail}", "active")

    def _on_download_done(self, last_filename: str | None) -> None:
        """Called on the main thread by Downloader when a download completes."""
        if self._download_completed:
            return
        self._download_completed = True
        self._last_filename = last_filename
        self.is_downloading = False
        self.act_bar.set(1.0)
        self.prog_detail.configure(text="")
        self.prog_pct.configure(text="")
        self._write_log(f"Download complete. Folder: {self.download_path}")
        self._close_dl_log()
        self._log_update("Download complete!", "success")
        self._log(f"Saved to {self._short_path(self.download_path)}", "dim")
        self._pill("Done")
        self.dl_btn.configure(state="normal")
        self.paste_btn.configure(state="normal")
        self._show_dl_footer()

        # History entry is built here on the main thread
        if self.info:
            entry = {
                "title":         self.info.get("title", "Unknown"),
                "url":           self._current_url,
                "thumbnail_url": self.info.get("thumbnail", ""),
                "video_id":      self.info.get("id", ""),
                "uploader":      self.info.get("uploader", ""),
                "duration":      self.info.get("duration_string", ""),
                "format":        self._current_fmt,
                "quality":       self._current_quality,
                "save_path":     self.download_path,
                "file_path":     last_filename or "",
                "log_path":      self._dl_log_path or "",
                "downloaded_at": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            }
            self.history = history.append(self.history, entry)
            thumb_url = entry["thumbnail_url"]
            video_id  = entry["video_id"]
            if thumb_url and video_id:
                threading.Thread(target=self._fetch_thumb,
                                 args=(thumb_url, video_id),
                                 daemon=True).start()

        self._refresh_history()

        # Completion actions from picker checkboxes
        fp = (last_filename
              if last_filename and os.path.isfile(last_filename)
              else None)
        if self._opt_open_when_done.get() and fp:
            try:
                subprocess.Popen(["open", fp])
            except Exception:
                pass
        if self._opt_show_in_folder.get():
            try:
                target = fp if fp else self.download_path
                cmd = ["open", "-R", target] if fp else ["open", target]
                subprocess.Popen(cmd)
            except Exception:
                pass

    def _on_download_error(self, error: str) -> None:
        self.is_downloading = False
        self._write_log(f"Download failed: {error}")
        self._close_dl_log()
        self._log_update(f"Failed: {error[:80]}", "error")
        self._pill("Error")
        self.dl_btn.configure(state="normal")
        self.paste_btn.configure(state="normal")
        self._show_dl_footer()
        messagebox.showerror("Download Error", error[:300])

    # ── Thumbnails ────────────────────────────────────────────────────────────

    def _fetch_thumb(self, thumb_url: str, video_id: str) -> None:
        path = os.path.join(history.THUMB_CACHE, f"{video_id}.jpg")
        if not os.path.exists(path):
            try:
                req = urllib.request.Request(
                    thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    with open(path, "wb") as f:
                        f.write(r.read())
            except Exception:
                return
        self._ui(self._refresh_history)

    def _load_thumb(self, video_id: str,
                    w: int = HIST_TW, h: int = HIST_TH):
        if not _PILLOW:
            return None
        path = os.path.join(history.THUMB_CACHE, f"{video_id}.jpg")
        if not os.path.exists(path):
            return None
        try:
            img     = Image.open(path).convert("RGB")
            img     = img.resize((w, h), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, size=(w, h))
            self._thumb_refs[video_id] = ctk_img
            return ctk_img
        except Exception:
            return None

    # ── History rendering ─────────────────────────────────────────────────────

    def _refresh_history(self) -> None:
        for w in self._history_rows:
            try:
                w.destroy()
            except Exception:
                pass
        self._history_rows = []

        n = len(self.history)
        self.hist_count.configure(
            text=f"{n} item{'s' if n != 1 else ''}" if n else "")

        if not self.history:
            lbl = ctk.CTkLabel(self.hist_scroll, text="No downloads yet",
                                font=("Helvetica", 12),
                                text_color=MUTED,
                                fg_color="transparent")
            lbl.pack(pady=24)
            self._history_rows.append(lbl)
            return

        for entry in self.history:
            self._render_row(entry)

    def _render_row(self, entry: dict) -> None:
        card = ctk.CTkFrame(self.hist_scroll, fg_color=CARD,
                             corner_radius=14,
                             border_color=BORDER, border_width=1)
        card.pack(fill="x", pady=(0, 8))
        self._history_rows.append(card)

        inner = ctk.CTkFrame(card, fg_color=CARD, corner_radius=0)
        inner.pack(fill="x", padx=14, pady=12)

        file_path   = entry.get("file_path", "")
        file_exists = bool(file_path and os.path.isfile(file_path))

        thumb_box = ctk.CTkFrame(inner, fg_color="#c8e6d4",
                                  corner_radius=8,
                                  width=HIST_TW, height=HIST_TH)
        thumb_box.pack(side="left")
        thumb_box.pack_propagate(False)

        photo = self._load_thumb(entry.get("video_id", ""))
        if photo:
            ctk.CTkLabel(thumb_box, image=photo, text="",
                         fg_color="#1c1c1e",
                         corner_radius=8).pack(fill="both", expand=True)
            thumb_box.configure(fg_color="#1c1c1e")
        else:
            ctk.CTkLabel(thumb_box, text="▶",
                         font=("Helvetica", 14),
                         text_color=ACCENT,
                         fg_color="transparent").pack(expand=True)

        text_f = ctk.CTkFrame(inner, fg_color=CARD, corner_radius=0)
        text_f.pack(side="left", fill="x", expand=True, padx=(12, 0))

        title = entry.get("title", "Unknown")
        ctk.CTkLabel(text_f, text=title[:56],
                     font=("Helvetica", 12, "bold"),
                     text_color=FG,
                     fg_color="transparent",
                     anchor="w").pack(fill="x")

        meta_parts = []
        dt = entry.get("downloaded_at", "")
        if dt:
            meta_parts.append(dt[:10])
        save_path = entry.get("save_path", "")
        if save_path:
            meta_parts.append(self._short_path(save_path))
        if file_path and not file_exists:
            meta_parts.append("⚠ file removed")

        ctk.CTkLabel(text_f,
                     text="  ·  ".join(meta_parts),
                     font=("Helvetica", 10),
                     text_color="#cc3333" if (file_path and not file_exists)
                                         else MUTED,
                     fg_color="transparent",
                     anchor="w").pack(fill="x", pady=(3, 0))

        right = ctk.CTkFrame(inner, fg_color=CARD, corner_radius=0)
        right.pack(side="right", padx=(8, 0))

        fmt = entry.get("format", "").upper()
        if fmt:
            ctk.CTkLabel(right, text=fmt,
                         font=("Helvetica", 10, "bold"),
                         fg_color=PILL_BG,
                         text_color=PILL_FG,
                         corner_radius=10,
                         padx=8, pady=2).pack(anchor="e")

        if save_path and os.path.isdir(save_path):
            ctk.CTkButton(right, text="⌁ Finder",
                          font=("Helvetica", 10, "bold"),
                          fg_color="transparent",
                          hover_color="#f0ede8",
                          text_color=ACCENT,
                          corner_radius=8,
                          border_width=0,
                          height=24,
                          command=lambda p=save_path: os.system(f'open "{p}"')
                          ).pack(anchor="e", pady=(6, 0))

        menu_btn = ctk.CTkButton(right, text="···",
                                  font=("Helvetica", 14, "bold"),
                                  fg_color="transparent",
                                  hover_color="#f0ede8",
                                  text_color=MUTED,
                                  corner_radius=8,
                                  border_width=0,
                                  height=24, width=32)
        menu_btn.pack(anchor="e", pady=(4, 0))
        menu_btn.configure(
            command=lambda e=entry, b=menu_btn: self._show_row_menu(b, e))

    # ── Row context menu ──────────────────────────────────────────────────────

    def _show_row_menu(self, btn, entry: dict) -> None:
        menu = tk.Menu(self.root, tearoff=0, font=("Helvetica", 12),
                       bg=CARD, fg=FG,
                       activebackground=ACCENT, activeforeground="#fff",
                       relief="flat", bd=0)

        save_path   = entry.get("save_path", "")
        log_path    = entry.get("log_path", "")
        file_path   = entry.get("file_path", "")
        url         = entry.get("url", "")
        file_exists = bool(file_path and os.path.isfile(file_path))

        if save_path and os.path.isdir(save_path):
            menu.add_command(label="View Folder",
                             command=lambda: os.system(f'open "{save_path}"'))
        else:
            menu.add_command(label="View Folder", state="disabled")

        if log_path and os.path.isfile(log_path):
            menu.add_command(label="View Process Log",
                             command=lambda: os.system(f'open -e "{log_path}"'))
        else:
            menu.add_command(label="View Process Log", state="disabled")

        menu.add_separator()

        if file_exists:
            menu.add_command(label="Delete File",
                             command=lambda: self._delete_file(entry))
        else:
            menu.add_command(label="Delete File", state="disabled")

        menu.add_command(label="Delete from History",
                         command=lambda: self._delete_from_history(entry))

        if file_exists:
            menu.add_command(label="Delete Both",
                             command=lambda: self._delete_both(entry))
        else:
            menu.add_command(label="Delete Both", state="disabled")

        menu.add_separator()

        if url:
            menu.add_command(label="Open on YouTube",
                             command=lambda: webbrowser.open(url))
        else:
            menu.add_command(label="Open on YouTube", state="disabled")

        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _delete_file(self, entry: dict) -> None:
        file_path = entry.get("file_path", "")
        if not file_path or not os.path.isfile(file_path):
            messagebox.showwarning("File Not Found",
                                   "The file could not be found on disk.")
            return
        if messagebox.askyesno(
                "Delete File",
                f'Permanently delete:\n"{os.path.basename(file_path)}"'
                f'\n\nThis cannot be undone.'):
            try:
                os.remove(file_path)
                entry["file_path"] = ""
                history.save(self.history)
                self._refresh_history()
            except Exception as e:
                messagebox.showerror("Delete Failed", str(e))

    def _delete_from_history(self, entry: dict) -> None:
        title = entry.get("title", "this item")
        if messagebox.askyesno(
                "Delete from History",
                f'Remove "{title[:60]}" from history?\n\n'
                f'The downloaded file will not be deleted.'):
            try:
                self.history.remove(entry)
            except ValueError:
                pass
            history.save(self.history)
            self._refresh_history()

    def _delete_both(self, entry: dict) -> None:
        file_path = entry.get("file_path", "")
        if not file_path or not os.path.isfile(file_path):
            messagebox.showwarning("File Not Found",
                                   "The file could not be found on disk.")
            return
        if messagebox.askyesno(
                "Delete Both",
                f'Permanently delete the file and remove from history?\n\n'
                f'"{os.path.basename(file_path)}"\n\nThis cannot be undone.'):
            try:
                os.remove(file_path)
            except Exception as e:
                messagebox.showerror("Delete Failed", str(e))
                return
            try:
                self.history.remove(entry)
            except ValueError:
                pass
            history.save(self.history)
            self._refresh_history()

    # ── Browser integration ───────────────────────────────────────────────────

    def _build_browser_panel(self) -> None:
        bp = BrowserPanel(
            self.root,
            on_back    = self._wv_go_back,
            on_forward = self._wv_go_forward,
            on_reload  = self._wv_reload,
            on_close   = self._close_browser,
            on_navigate= self._wv_navigate,
        )
        self._browser_panel_obj = bp
        self._browser_panel     = bp.panel
        self._browser_nav_h     = bp.nav_h
        self._browser_url_entry = bp.url_entry
        self._browser_url_var   = bp.url_var
        # Wire FocusOut → return keyboard focus to WKWebView
        bp.url_entry.bind("<FocusOut>", lambda e: self._return_focus_to_wv())

    def _open_browser(self) -> None:
        if self._browser_visible:
            return
        self._browser_visible = True
        self._wv_last_url   = ""
        self._wv_poll_count = 0

        self._pre_browser_w = self.root.winfo_width()
        self.root.resizable(True, True)
        self.root.minsize(1000, 600)
        if self._pre_browser_w < 1100:
            self.root.geometry(f"1100x{self.root.winfo_height()}")

        self.root.update_idletasks()
        win_h = self.root.winfo_height()

        self._browser_panel.place(x=0, y=-win_h, relwidth=1, relheight=1)
        self._browser_panel.lift()
        self.root.focus_set()

        self.root.after(20,  self._embed_wkwebview)
        self.root.after(600, self._wv_poll)

        self._animate_browser(step=0, total_h=win_h, direction="in")

    def _close_browser(self) -> None:
        if not self._browser_visible:
            return
        win_h = self.root.winfo_height()
        self._animate_browser(step=0, total_h=win_h, direction="out")

    def _animate_browser(self, step: int, total_h: int,
                          direction: str) -> None:
        STEPS = 48
        t = step / STEPS
        ease = (4.0 * t ** 3) if t < 0.5 else (1.0 - (-2.0 * t + 2.0) ** 3 / 2.0)

        if direction == "in":
            y = int(-total_h * (1.0 - ease))
        else:
            y = int(-total_h * ease)

        try:
            self._browser_panel.place(y=y)
        except Exception:
            return

        if step < STEPS:
            self.root.after(16, lambda:
                self._animate_browser(step + 1, total_h, direction))
        elif direction == "out":
            self._browser_panel.place_forget()
            self._browser_visible = False
            if self._wkwebview:
                try:
                    self._wkwebview.removeFromSuperview()
                except Exception:
                    pass
                self._wkwebview = None
            self.root.minsize(580, 600)
            self.root.resizable(False, True)
            self.root.geometry(f"{self._pre_browser_w}x{self.root.winfo_height()}")

    # ── WKWebView embedding ───────────────────────────────────────────────────

    def _embed_wkwebview(self) -> None:
        if not HAS_WKWEBVIEW or self._wkwebview is not None:
            return
        try:
            self._do_embed_wkwebview()
        except Exception as exc:
            self._log(f"[browser] WKWebView init error: {exc}", "muted")

    def _do_embed_wkwebview(self) -> None:
        from Foundation import NSURL, NSURLRequest
        from AppKit import NSApplication
        from AppKit import NSMakeRect
        from WebKit import (WKWebView, WKWebViewConfiguration,
                            WKUserScript, WKUserContentController)

        self.root.update_idletasks()
        nswin = None
        for w in NSApplication.sharedApplication().windows():
            if w.title() == "Canopy":
                nswin = w
                break
        if nswin is None:
            return
        self._wv_nswin = nswin
        cv = nswin.contentView()

        bounds = cv.bounds()
        cv_w   = bounds.size.width
        cv_h   = bounds.size.height
        nav_h  = self._browser_nav_h   # 59 px (nav 58 + divider 1)

        wv_frame = NSMakeRect(0, 0, cv_w, cv_h - nav_h)

        config = WKWebViewConfiguration.new()
        ctrl   = WKUserContentController.new()
        script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            WEBVIEW_JS, 1, False,
        )
        ctrl.addUserScript_(script)
        config.setUserContentController_(ctrl)

        wv = WKWebView.alloc().initWithFrame_configuration_(wv_frame, config)
        wv.setCustomUserAgent_(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        cv.addSubview_(wv)
        self._wkwebview = wv
        nswin.makeFirstResponder_(wv)

        self.root.bind("<Configure>", self._on_window_configure, add="+")
        url = NSURL.URLWithString_("https://www.youtube.com")
        wv.loadRequest_(NSURLRequest.requestWithURL_(url))

    # ── WKWebView polling ─────────────────────────────────────────────────────

    def _wv_poll(self) -> None:
        if not self._wkwebview or not self._browser_visible:
            return
        try:
            url_obj = self._wkwebview.URL()
            if url_obj:
                url_str = str(url_obj.absoluteString())
                if "#__canopy_dl__:" in url_str:
                    import urllib.parse
                    fragment = url_str.split("#__canopy_dl__:", 1)[1]
                    dl_url   = urllib.parse.unquote(fragment)
                    self._wkwebview.evaluateJavaScript_completionHandler_(
                        "if(location.hash.startsWith('#__canopy_dl__:')){"
                        "(window.__cpwv_orig_replace||history.replaceState)"
                        ".call(history,null,'',location.pathname+location.search);}",
                        None,
                    )
                    if any(dl_url.startswith(p) for p in _ALLOWED_PREFIXES):
                        self._browser_trigger_download(dl_url)
                elif url_str and url_str != "about:blank":
                    if url_str != self._wv_last_url:
                        self._wv_last_url = url_str
                        self._on_wv_nav(url_str)
                        try:
                            self._wkwebview.evaluateJavaScript_completionHandler_(
                                "if(typeof window.updateDlBtn==='function'){"
                                "window.updateDlBtn();"
                                "setTimeout(window.updateDlBtn,600);"
                                "setTimeout(window.updateDlBtn,1500);}",
                                None,
                            )
                        except Exception:
                            pass
        except Exception:
            pass

        self._wv_poll_count += 1
        if self._wv_poll_count % 20 == 0:
            try:
                self._wkwebview.evaluateJavaScript_completionHandler_(
                    "window.__cpwv=false;" + WEBVIEW_JS, None
                )
            except Exception:
                pass

        if self._browser_visible:
            self.root.after(300, self._wv_poll)

    def _on_wv_nav(self, url: str) -> None:
        if self._browser_url_var:
            self._browser_url_var.set(url)

    # ── WKWebView nav actions ─────────────────────────────────────────────────

    def _return_focus_to_wv(self) -> None:
        if self._wkwebview and self._wv_nswin:
            try:
                self._wv_nswin.makeFirstResponder_(self._wkwebview)
            except Exception:
                pass

    def _wv_navigate(self, url: str | None = None) -> None:
        if not self._wkwebview:
            return
        from Foundation import NSURL, NSURLRequest
        target = (url or "").strip()
        if not target:
            return
        if target.startswith("file://"):
            return   # security: block local filesystem access
        if not target.startswith(("http://", "https://")):
            target = "https://" + target
        self._wkwebview.loadRequest_(
            NSURLRequest.requestWithURL_(NSURL.URLWithString_(target)))
        self._return_focus_to_wv()

    def _wv_go_back(self) -> None:
        if self._wkwebview:
            self._wkwebview.goBack()

    def _wv_go_forward(self) -> None:
        if self._wkwebview:
            self._wkwebview.goForward()

    def _wv_reload(self) -> None:
        if self._wkwebview:
            self._wkwebview.reload_(None)

    def _on_window_configure(self, event) -> None:
        if self._wkwebview and self._wv_nswin:
            try:
                from AppKit import NSMakeRect
                cv     = self._wv_nswin.contentView()
                bounds = cv.bounds()
                nav_h  = self._browser_nav_h
                self._wkwebview.setFrame_(
                    NSMakeRect(0, 0, bounds.size.width,
                               bounds.size.height - nav_h))
            except Exception:
                pass

    def _browser_trigger_download(self, url: str) -> None:
        self._close_browser()
        self._current_url = url
        self._fetch_info()

    # ── About panel ───────────────────────────────────────────────────────────

    def _show_about(self) -> None:
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.configure(fg_color=CARD)
        dlg.transient(self.root)
        dlg.grab_set()

        W = 320
        content = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=0)
        content.pack(fill="x", padx=32, pady=(32, 28))

        mark_img = _load_brand_mark(64)
        if mark_img:
            self._about_mark_ref = mark_img
            ctk.CTkLabel(content, image=mark_img, text="",
                         fg_color="transparent").pack()

        ctk.CTkLabel(content, text="C A N O P Y",
                     font=("Helvetica Neue", 15),
                     text_color=FG,
                     fg_color="transparent").pack(pady=(14, 4))

        ctk.CTkLabel(content,
                     text="YouTube Downloader for creators",
                     font=("Helvetica", 11),
                     text_color=MUTED,
                     fg_color="transparent").pack()

        ctk.CTkLabel(content, text=f"Version {VERSION}",
                     font=("Helvetica", 10),
                     text_color=DIM,
                     fg_color="transparent").pack(pady=(4, 0))

        ctk.CTkFrame(content, fg_color=BORDER, height=1,
                     corner_radius=0).pack(fill="x", pady=(20, 16))

        ctk.CTkLabel(content,
                     text="Built with yt-dlp · CustomTkinter · pywebview",
                     font=("Helvetica", 10),
                     text_color=DIM,
                     fg_color="transparent").pack()

        ctk.CTkButton(dlg, text="Close",
                      font=("Helvetica", 12),
                      fg_color=ACCENT, hover_color="#3d6b4a",
                      text_color="#ffffff",
                      corner_radius=10, height=38,
                      command=dlg.destroy).pack(fill="x", padx=32, pady=(0, 28))

        dlg.update_idletasks()
        dh = dlg.winfo_reqheight()
        x  = self.root.winfo_x() + (self.root.winfo_width()  - W) // 2
        y  = self.root.winfo_y() + (self.root.winfo_height() - dh) // 2
        dlg.geometry(f"{W}x{dh}+{x}+{y}")

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _short_path(self, path: str) -> str:
        home = os.path.expanduser("~")
        return ("~" + path[len(home):]) if path.startswith(home) else path
