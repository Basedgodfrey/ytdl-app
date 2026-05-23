import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import threading
import queue
import subprocess
import yt_dlp
import os
import sys
import json
import urllib.request
import datetime
import webbrowser

try:
    from PIL import Image
    PILLOW = True
except ImportError:
    PILLOW = False

# WKWebView embedded directly in the app window (via pyobjc — installed with pywebview)
try:
    from AppKit import NSApplication, NSMakeRect
    from WebKit import (WKWebView, WKWebViewConfiguration,
                        WKUserScript, WKUserContentController)
    HAS_WKWEBVIEW = True
except Exception:
    HAS_WKWEBVIEW = False


def _assets_path(filename):
    """Resolve a file inside the assets/ folder for both dev and PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets", filename)


def _load_brand_mark(size: int = 32):
    """Load canopy-green-512.png and return a CTkImage at *size* logical pt."""
    if not PILLOW:
        return None
    path = _assets_path("canopy-green-512.png")
    if not os.path.exists(path):
        return None
    try:
        src = Image.open(path).convert("RGBA")
        return ctk.CTkImage(light_image=src, size=(size, size))
    except Exception:
        return None


def _set_dock_icon():
    """Set the macOS dock icon at runtime using the 512px icon PNG."""
    if not PILLOW:
        return
    path = _assets_path("canopy-icon-512.png")
    if not os.path.exists(path):
        return
    try:
        # Use AppKit (available via pyobjc, installed with pywebview)
        from AppKit import NSApplication, NSImage
        ns_img = NSImage.alloc().initWithContentsOfFile_(path)
        if ns_img:
            NSApplication.sharedApplication().setApplicationIconImage_(ns_img)
    except Exception:
        pass

HISTORY_FILE = os.path.expanduser("~/.ytdl_history.json")
THUMB_CACHE  = os.path.expanduser("~/.ytdl_cache/thumbnails")
LOG_FILE     = os.path.expanduser("~/.ytdl_debug.log")
DL_LOGS_DIR  = os.path.expanduser("~/.ytdl_cache/logs")

BG       = "#f5f3ee"
TITLEBAR = "#eeeae2"
CARD     = "#ffffff"
BORDER   = "#dedad3"
ACCENT   = "#4a7c59"
FG       = "#2a2520"
MUTED    = "#9e9890"
DIM      = "#b5b0a8"
PILL_BG  = "#dff0e6"
PILL_FG  = "#3b6d45"
LOG_BG   = "#1a1a18"
LOG_GRN  = "#4ec97b"
LOG_MUT  = "#7a7a70"
LOG_DIM  = "#4a4a42"
PROG_TRK = "#ece9e3"

FONT_MONO = ("Menlo", 10)
THUMB_W, THUMB_H = 536, 220   # full-width banner thumbnail in info card
HIST_TW,  HIST_TH  = 68, 44

# ── Inline WKWebView JS (injected as WKUserScript — no nav bar, tkinter owns that) ──
# Adds floating "Download with Canopy" pill on video pages.
# Signals Python by setting location.hash = '#__canopy_dl__:<url>' (polled every 300 ms).

WEBVIEW_JS = """
(function () {
    'use strict';
    var ACCENT = '#4a7c59';

    /* Store TRUE originals once — re-injection never double-wraps */
    if (!window.__cpwv_orig_push)    window.__cpwv_orig_push    = history.pushState;
    if (!window.__cpwv_orig_replace) window.__cpwv_orig_replace = history.replaceState;

    /* idempotency guard — skip full setup if hooks already live */
    if (window.__cpwv) { if (typeof window.updateDlBtn === 'function') window.updateDlBtn(); return; }
    window.__cpwv = true;

    window.updateDlBtn = function updateDlBtn() {
        var url = location.href;
        var isVideo = /[?&]v=/.test(url) || /[/]shorts[/]/.test(url);
        var btn = document.getElementById('__cpdl');
        if (isVideo && !btn) {
            btn = document.createElement('div');
            btn.id = '__cpdl';
            btn.innerHTML = '⬇︎  Download with Canopy';
            btn.style.cssText =
                'position:fixed;bottom:28px;right:28px;' +
                'background:' + ACCENT + ';color:#fff;' +
                'font-family:-apple-system,BlinkMacSystemFont,sans-serif;' +
                'font-size:13px;font-weight:600;' +
                'padding:11px 22px;border-radius:50px;cursor:pointer;' +
                'z-index:2147483647;user-select:none;' +
                'box-shadow:0 4px 18px rgba(74,124,89,.45);' +
                'transition:transform .15s,box-shadow .15s;';
            btn.onmouseenter = function() {
                btn.style.transform = 'scale(1.05)';
                btn.style.boxShadow = '0 6px 24px rgba(74,124,89,.6)';
            };
            btn.onmouseleave = function() {
                btn.style.transform = '';
                btn.style.boxShadow = '0 4px 18px rgba(74,124,89,.45)';
            };
            btn.onclick = function() {
                /* Use stored original replaceState so our hook doesn't intercept */
                var videoUrl = location.href.split('#')[0];
                try { window.__cpwv_orig_replace.call(history, null, '',
                    '#__canopy_dl__:' + encodeURIComponent(videoUrl)); } catch(e) {}
                btn.innerHTML = '✓  Sent to Canopy';
                btn.style.background = '#3b6d45';
                setTimeout(function() {
                    btn.innerHTML = '⬇︎  Download with Canopy';
                    btn.style.background = ACCENT;
                }, 2000);
            };
            document.body.appendChild(btn);
        } else if (!isVideo && btn) {
            btn.remove();
        }
    };

    /* SPA navigation hooks — always wrap TRUE originals, not prior wrappers */
    history.pushState = function() {
        window.__cpwv_orig_push.apply(this, arguments);
        setTimeout(window.updateDlBtn, 400);
        setTimeout(window.updateDlBtn, 1200);
    };
    history.replaceState = function() {
        window.__cpwv_orig_replace.apply(this, arguments);
        if (!location.hash || !location.hash.startsWith('#__canopy_dl__:'))
            setTimeout(window.updateDlBtn, 400);
    };
    window.addEventListener('popstate', function() { setTimeout(window.updateDlBtn, 300); });

    /* In-page polling fallback for navigations that bypass all hooks */
    var _lh = location.href.split('#')[0];
    setInterval(function() {
        var c = location.href.split('#')[0];
        if (c !== _lh) { _lh = c; setTimeout(window.updateDlBtn, 350); }
    }, 700);

    window.updateDlBtn();
    setTimeout(window.updateDlBtn,  500);
    setTimeout(window.updateDlBtn, 1500);
    setTimeout(window.updateDlBtn, 3000);
})();
"""


# No ObjC delegate classes — all browser↔Python communication uses polling
# (WKWebView.URL() is a safe Python→ObjC call; ObjC→Python callbacks crash Python 3.14)


# ── ffmpeg helper ─────────────────────────────────────────────────────────────

def _find_ffmpeg():
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "ffmpeg")
        if os.path.isfile(bundled):
            return bundled
    homebrew = "/opt/homebrew/bin/ffmpeg"
    if os.path.isfile(homebrew):
        return homebrew
    import shutil
    return shutil.which("ffmpeg")


FFMPEG_PATH = _find_ffmpeg()


# ── Download progress formatting helpers (Chrome-style) ──────────────────────

def _fmt_bytes(n):
    """Human-readable byte size."""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.2f} GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"

def _fmt_speed(bps):
    """Human-readable bytes/second speed."""
    if bps >= 1_073_741_824:
        return f"{bps / 1_073_741_824:.2f} GB/s"
    if bps >= 1_048_576:
        return f"{bps / 1_048_576:.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps:.0f} B/s"

def _fmt_eta(sec):
    """Human-readable time remaining (Chrome-style)."""
    sec = int(sec)
    if sec < 1:
        return "< 1 sec"
    if sec < 60:
        return f"{sec} sec"
    if sec < 3600:
        m, s = divmod(sec, 60)
        return f"{m} min {s} sec" if s else f"{m} min"
    h, rem = divmod(sec, 3600)
    m = rem // 60
    return f"{h} hr {m} min" if m else f"{h} hr"


class YtdlLogger:
    def __init__(self, write_fn):
        self._write = write_fn

    def debug(self, msg):
        if msg.startswith("[debug]"):
            return
        self._write(f"[yt-dlp] {msg}")

    def info(self, msg):
        self._write(f"[yt-dlp] {msg}")

    def warning(self, msg):
        self._write(f"[yt-dlp WARN] {msg}")

    def error(self, msg):
        self._write(f"[yt-dlp ERROR] {msg}")


class CanopyApp:
    def __init__(self, root):
        self.root = root

        # Thread-safe UI queue — background threads push callables here;
        # only the main thread ever calls root.after(), avoiding the
        # PyEval_RestoreThread(NULL) crash in Python 3.14.
        self._ui_q = queue.Queue()
        self._poll_ui_q()

        self.root.title("Canopy")
        self.root.geometry("580x860")
        self.root.minsize(580, 600)
        self.root.resizable(False, True)
        self.root.configure(fg_color=BG)

        self.download_path         = os.path.expanduser("~/Downloads")
        self._current_url          = ""      # URL set by Paste Link or browser trigger
        self.info                  = None
        self.is_fetching           = False
        self.is_downloading        = False
        self.activity_open         = True
        self._thumb_refs           = {}
        self._dl_log_handle        = None
        self._dl_log_path          = None
        self._last_log_replaceable = False
        self._download_completed   = False
        self._history_rows         = []

        # Inline WKWebView browser state
        self._wkwebview         = None   # WKWebView NSView instance
        self._wv_nswin          = None   # Canopy NSWindow reference
        self._browser_panel     = None   # tkinter overlay frame
        self._browser_url_entry = None   # CTkEntry in browser nav bar
        self._browser_visible   = False
        self._wv_poll_count     = 0
        self._wv_last_url       = ''     # last URL seen by poll — prevents 300ms reset
        self._pre_browser_w     = 580    # saved window width before browser opens

        self.format_var  = tk.StringVar(value="MP4")
        self.quality_var = tk.StringVar(value="Best")

        # Download completion preferences (set via picker checkboxes)
        self._opt_show_in_folder = tk.BooleanVar(value=False)
        self._opt_open_when_done = tk.BooleanVar(value=False)

        self.history = self._load_history()
        os.makedirs(THUMB_CACHE, exist_ok=True)
        os.makedirs(DL_LOGS_DIR, exist_ok=True)
        self._setup_log()
        _set_dock_icon()
        self._build_ui()
        self._refresh_history()

    # ── Thread-safe UI dispatch ───────────────────────────────────────────────

    def _ui(self, fn):
        """Call from any thread to schedule fn() on the main thread.
        Never calls root.after() directly from a background thread —
        that triggers PyEval_RestoreThread(NULL) in Python 3.14."""
        self._ui_q.put(fn)

    def _poll_ui_q(self):
        """Drain the UI queue and reschedule — runs only on the main thread."""
        try:
            while True:
                fn = self._ui_q.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.root.after(16, self._poll_ui_q)   # ~60 fps polling

    # ── Logging ──────────────────────────────────────────────────────────────

    def _setup_log(self):
        # Truncate log if it has grown past 5 MB to prevent unbounded disk growth
        try:
            if os.path.getsize(LOG_FILE) > 5 * 1024 * 1024:
                open(LOG_FILE, "w").close()
        except OSError:
            pass
        self._log_file = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
        self._write_log("=" * 60)
        self._write_log(f"Canopy session started  ffmpeg={FFMPEG_PATH or 'NOT FOUND'}")

    def _write_log(self, msg):
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

    def _open_dl_log(self, video_id, title):
        self._close_dl_log()
        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{ts}_{video_id}.txt"
        path  = os.path.join(DL_LOGS_DIR, fname)
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

    def _close_dl_log(self):
        if self._dl_log_handle:
            try:
                self._dl_log_handle.write("\n[END OF LOG]\n")
                self._dl_log_handle.close()
            except Exception:
                pass
            self._dl_log_handle = None

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save_history(self):
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(self.history, f, indent=2)
        except Exception:
            pass

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        PAD = 22

        # Title bar
        tbar = ctk.CTkFrame(self.root, fg_color=TITLEBAR, corner_radius=0, height=44)
        tbar.pack(fill="x")
        tbar.pack_propagate(False)

        # "Paste Link" button — left side of title bar
        self.paste_btn = ctk.CTkButton(
            tbar, text="⎘  Paste Link",
            font=("Helvetica", 13, "bold"),
            fg_color=ACCENT, hover_color="#3d6b4a", text_color="#ffffff",
            corner_radius=20, width=128, height=30,
            command=self._paste_link,
        )
        self.paste_btn.place(relx=0.0, rely=0.5, anchor="w", x=PAD)

        # ── Centered brand mark + wordmark ──────────────────────────────────
        brand_frame = ctk.CTkFrame(tbar, fg_color="transparent", corner_radius=0)
        brand_frame.place(relx=0.5, rely=0.5, anchor="center")

        brand_img = _load_brand_mark(32)
        if brand_img:
            ctk.CTkLabel(brand_frame, image=brand_img, text="",
                         fg_color="transparent").pack(side="left")
            self._brand_img_ref = brand_img   # prevent GC

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

        ctk.CTkFrame(self.root, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

        # ── Browser bar — pill at the top of the content area ────────────────
        bb_row = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        bb_row.pack(fill="x", padx=PAD, pady=(10, 0))

        bb_pill = ctk.CTkFrame(bb_row, fg_color=CARD, corner_radius=10,
                                border_color=BORDER, border_width=1,
                                cursor="hand2")
        bb_pill.pack(fill="x")

        bb_inner = ctk.CTkFrame(bb_pill, fg_color="transparent", corner_radius=0)
        bb_inner.pack(fill="x", padx=12, pady=9)

        self._bb_icon = ctk.CTkLabel(bb_inner, text="🌐",
                                      font=("Helvetica", 14), text_color=MUTED,
                                      fg_color="transparent", cursor="hand2")
        self._bb_icon.pack(side="left", padx=(0, 8))

        self._bb_label = ctk.CTkLabel(bb_inner, text="Click to open browser",
                                       font=("Helvetica", 13), text_color=MUTED,
                                       fg_color="transparent", anchor="w",
                                       cursor="hand2")
        self._bb_label.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(bb_inner, text="Open ↗",
                     font=("Helvetica", 11, "bold"), text_color=ACCENT,
                     fg_color="transparent", cursor="hand2").pack(side="right")

        def _bb_open(e=None):
            self._open_browser()

        for _w in [bb_pill, bb_inner] + list(bb_inner.winfo_children()):
            _w.bind("<Button-1>", _bb_open)

        # Body
        body = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        body.pack(fill="x")

        inner = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        inner.pack(fill="x", padx=PAD, pady=(14, 0))

        # Video info card
        self.video_card = ctk.CTkFrame(inner, fg_color=CARD,
                                        corner_radius=14,
                                        border_color=BORDER, border_width=1)
        self.video_card.pack(fill="x", pady=(0, 10))

        # ── Banner thumbnail (full-width, stacked on top) ──────────────────────
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

        # ── Text section below thumbnail ────────────────────────────────────
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

        ctk.CTkFrame(opts_row, fg_color=BG, width=8, corner_radius=0).pack(side="left")

        self._opt_qual = self._option_card(opts_row, "QUALITY", self.quality_var,
                                           ["Best", "4K", "1080p", "720p", "480p", "360p"])
        self._opt_qual.pack(side="left", fill="x", expand=True)

        ctk.CTkFrame(opts_row, fg_color=BG, width=8, corner_radius=0).pack(side="left")

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

        # Bind the entire save_card widget tree so any click triggers folder picker
        def _bind_tree(widget):
            widget.bind("<Button-1>", _pick_click)
            for child in widget.winfo_children():
                _bind_tree(child)
        _bind_tree(save_card)

        self.format_var.trace_add("write",  lambda *_: self._sync_pills())
        self.quality_var.trace_add("write", lambda *_: self._sync_pills())

        # Progress card
        self._build_progress_card(inner)

        ctk.CTkFrame(self.root, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

        # Sticky download footer (built but hidden until video is fetched)
        self._build_dl_footer(PAD)

        self._build_history_section(PAD)

    # ── Sticky download footer ────────────────────────────────────────────────

    _DL_FOOTER_H  = 74   # total height: 1px separator + 50px btn + 12+12 pady
    _dl_footer_on = False

    def _build_dl_footer(self, pad):
        """Build the sticky download footer using place() so it always pins to
        the window's bottom edge regardless of the pack layout below."""
        self._dl_pad = pad

        # Outer frame — placed over the window, not part of the pack chain
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

        # Reposition whenever the window is resized
        self.root.bind("<Configure>", self._dl_footer_reposition, add="+")

    def _dl_footer_reposition(self, _e=None):
        if not self._dl_footer_on:
            return
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        self._dl_footer.place(x=0, y=h - self._DL_FOOTER_H,
                               width=w, height=self._DL_FOOTER_H)
        self._dl_footer.lift()

    def _show_dl_footer(self):
        self._dl_footer_on = True
        self._dl_footer_reposition()

    def _hide_dl_footer(self):
        self._dl_footer_on = False
        self._dl_footer.place_forget()

    def _option_card(self, parent, label, var, choices):
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

    def _sync_pills(self):
        fmt  = self.format_var.get()
        qual = self.quality_var.get()
        self.vc_fmt_pill.configure(text=fmt.upper())
        self.vc_qual_pill.configure(text=qual)

    def _build_progress_card(self, parent):
        self.prog_card = ctk.CTkFrame(parent, fg_color=CARD,
                                       corner_radius=14,
                                       border_color=BORDER, border_width=1)
        self.prog_card.pack(fill="x", pady=(0, 10))

        pc = ctk.CTkFrame(self.prog_card, fg_color=CARD, corner_radius=0)
        pc.pack(fill="x", padx=16, pady=(14, 10))

        # ── Row 1: Status label + live percentage ─────────────────────────────
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

        # ── Row 2: Progress bar (thicker for readability) ─────────────────────
        self.act_bar = ctk.CTkProgressBar(pc,
                                           fg_color=PROG_TRK,
                                           progress_color=ACCENT,
                                           corner_radius=99,
                                           height=8)
        self.act_bar.set(0)
        self.act_bar.pack(fill="x", pady=(10, 0))

        # ── Row 3: Size · speed · time remaining (Chrome-style) ───────────────
        self.prog_detail = ctk.CTkLabel(pc, text="",
                                         font=("Helvetica", 12),
                                         text_color=MUTED,
                                         fg_color="transparent",
                                         anchor="w")
        self.prog_detail.pack(fill="x", pady=(8, 0))

        tog_row = ctk.CTkFrame(pc, fg_color=CARD, corner_radius=0, cursor="hand2")
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

    def _build_history_section(self, PAD):
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

        # Build browser overlay panel (hidden until Browse is clicked)
        self._build_browser_panel()

    # ── Activity log helpers ──────────────────────────────────────────────────

    def _log(self, text, kind="muted"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_text.config(state="normal")
        self._log_text.insert("end", f"{ts}  ", "ts")
        self._log_text.insert("end", f"{text}\n", kind)
        self._log_text.config(state="disabled")
        self._log_text.see("end")
        self._last_log_replaceable = False

    def _log_update(self, text, kind="active"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_text.config(state="normal")
        if self._last_log_replaceable:
            self._log_text.delete("end-2l linestart", "end-1l linestart")
        self._log_text.insert("end", f"{ts}  {text}\n", kind)
        self._log_text.config(state="disabled")
        self._log_text.see("end")
        self._last_log_replaceable = True

    def _log_clear(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")
        self._last_log_replaceable = False

    def _pill(self, text, bg=None, fg=None):
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

    def _toggle_activity(self):
        self.activity_open = not self.activity_open
        if self.activity_open:
            self.log_body.pack(fill="x", pady=(6, 0))
            self.log_chevron.configure(text="▾")
        else:
            self.log_body.pack_forget()
            self.log_chevron.configure(text="▸")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _pick_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_path)
        if folder:
            self.download_path = folder
            self.folder_label.configure(text=self._short_path(folder))

    def _paste_link(self):
        """Read a URL from the system clipboard and kick off a fetch."""
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

    def _fetch_info(self):
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
        threading.Thread(target=self._do_fetch, args=(url,), daemon=True).start()

    def _do_fetch(self, url):
        self._write_log(f"Fetching info for: {url}")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                    "skip_download": True}) as ydl:
                self.info = ydl.extract_info(url, download=False)
            title     = self.info.get("title", "Unknown")
            uploader  = self.info.get("uploader", "")
            duration  = self.info.get("duration_string", "")
            thumb_url = self.info.get("thumbnail", "")
            video_id  = self.info.get("id", "")
            self._write_log(f"Info OK  title={title!r}")
            parts = [p for p in (uploader, duration) if p]
            meta  = "  ·  ".join(parts)
            self._ui(lambda t=title, m=meta, tu=thumb_url, vi=video_id:
                     self._on_fetch_done(t, m, tu, vi, True))
        except Exception as e:
            self._write_log(f"Fetch error: {e}")
            self._ui(lambda msg=str(e): self._on_fetch_done(msg, "", "", "", False))

    def _on_fetch_done(self, title, meta, thumb_url, video_id, success):
        self.is_fetching = False
        self.paste_btn.configure(state="normal")
        if success:
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
                                 args=(thumb_url, video_id), daemon=True).start()
        else:
            self.vc_title.configure(text="Could not fetch video info",
                                    text_color="#cc3333")
            self._log(f"Error: {title[:80]}", "error")
            self._pill("Error")

    def _load_vc_thumb(self, thumb_url, video_id):
        cached = os.path.join(THUMB_CACHE, f"{video_id}.jpg")
        if not os.path.exists(cached):
            try:
                req = urllib.request.Request(
                    thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    with open(cached, "wb") as f:
                        f.write(r.read())
            except Exception:
                return
        if PILLOW and os.path.exists(cached):
            try:
                img = Image.open(cached).convert("RGB")
                # Center-crop: scale so image fills full width, then crop
                # vertically to THUMB_H — no letterbox bars, always edge-to-edge.
                iw, ih  = img.size
                scale   = THUMB_W / iw          # scale to fill width exactly
                new_w   = THUMB_W
                new_h   = max(THUMB_H, int(ih * scale))
                img     = img.resize((new_w, new_h), Image.LANCZOS)
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

    def _start_download(self):
        if not self.info:
            return
        if self.is_downloading:
            messagebox.showwarning("Download In Progress",
                                   "A download is already running. Please wait.")
            return
        self._show_download_picker()

    # ── Browser integration ───────────────────────────────────────────────────

    # ── Browser panel (inline WKWebView inside this window) ─────────────────────

    def _build_browser_panel(self):
        """Build a full-window overlay panel that hosts the inline WKWebView.

        The panel is hidden initially.  The nav bar is a native tkinter widget;
        the WKWebView NSView is inserted directly into the window's content view
        below the nav bar so both are permanently inside the same NSWindow.
        """
        NAV_H = 58   # height of the Canopy-branded nav bar

        # Full-window overlay (plain tk.Frame so we get a clean NSView)
        panel = tk.Frame(self.root, bg=BG)
        self._browser_panel = panel

        # ── Nav bar shell (tk.Frame for height control + NSView compat) ──────
        nav_shell = tk.Frame(panel, bg=TITLEBAR, height=NAV_H)
        nav_shell.pack(fill="x")
        nav_shell.pack_propagate(False)

        # Inner CTkFrame for Canopy-styled content
        nav = ctk.CTkFrame(nav_shell, fg_color=TITLEBAR, corner_radius=0)
        nav.pack(fill="both", expand=True, padx=10, pady=9)

        # ── Icon buttons (CTkButton centers text exactly) ─────────────────────
        def _icon_btn(parent, text, cmd, size=20):
            return ctk.CTkButton(
                parent, text=text, command=cmd,
                font=("Helvetica Neue", size),
                fg_color="transparent",
                hover_color=BORDER,
                text_color=FG,
                corner_radius=8,
                width=36, height=36,
                cursor="hand2",
            )

        back_btn   = _icon_btn(nav, "‹", self._wv_go_back,   size=22)
        fwd_btn    = _icon_btn(nav, "›", self._wv_go_forward, size=22)
        reload_btn = _icon_btn(nav, "↺", self._wv_reload,     size=16)

        back_btn.pack(side="left")
        fwd_btn.pack(side="left", padx=(2, 0))
        reload_btn.pack(side="left", padx=(2, 8))

        # ── Close button — always right, red × ───────────────────────────────
        close_btn = ctk.CTkButton(
            nav, text="✕", command=self._close_browser,
            font=("Helvetica Neue", 13),
            fg_color="transparent",
            hover_color="#fde8e8",
            text_color="#c0392b",
            corner_radius=8,
            width=36, height=36,
            cursor="hand2",
        )
        close_btn.pack(side="right")

        # ── URL pill (rounded CARD-coloured frame, fills center) ──────────────
        url_pill = ctk.CTkFrame(nav, fg_color=CARD, corner_radius=10,
                                 border_color=BORDER, border_width=1)
        url_pill.pack(side="left", fill="x", expand=True, padx=(0, 6))

        url_var = tk.StringVar(value="https://www.youtube.com")
        url_entry = tk.Entry(
            url_pill, textvariable=url_var,
            bd=0, relief="flat",
            bg=CARD, fg=FG, insertbackground=FG,
            font=("Helvetica Neue", 13),
            highlightthickness=0,
        )
        url_entry.pack(side="left", fill="x", expand=True,
                       padx=(12, 0), ipady=5, pady=6)
        url_entry.bind("<Return>",   lambda e: self._wv_navigate(url_var.get()))
        url_entry.bind("<FocusIn>",  lambda e: None)
        url_entry.bind("<FocusOut>", lambda e: self._return_focus_to_wv())
        self._browser_url_entry = url_entry
        self._browser_url_var   = url_var

        # Go / navigate button inside the pill (right side)
        go_btn = ctk.CTkButton(
            url_pill, text="↵",
            font=("Helvetica Neue", 15),
            fg_color="transparent",
            hover_color=PILL_BG,
            text_color=ACCENT,
            corner_radius=8,
            width=36, height=28,
            cursor="hand2",
            command=lambda: self._wv_navigate(url_var.get()),
        )
        go_btn.pack(side="right", padx=(0, 4), pady=4)

        # Divider between nav bar and web content
        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x")

        # Store nav height so embed knows where to start
        self._browser_nav_h = NAV_H + 1   # +1 for divider

    # ── Browser open / close / animate ───────────────────────────────────────

    def _open_browser(self):
        """Slide the browser panel into view and embed WKWebView inside it."""
        if self._browser_visible:
            return
        self._browser_visible = True
        self._wv_last_url     = ''   # reset so URL bar updates on first poll
        self._wv_poll_count   = 0    # reset so re-injection fires promptly

        # Expand window so YouTube renders its full desktop layout (needs ~1000 px+)
        self._pre_browser_w = self.root.winfo_width()
        self.root.resizable(True, True)
        self.root.minsize(1000, 600)
        if self._pre_browser_w < 1100:
            self.root.geometry(f"1100x{self.root.winfo_height()}")

        self.root.update_idletasks()
        win_h = self.root.winfo_height()

        # Place panel initially one full window-height above the visible area
        self._browser_panel.place(x=0, y=-win_h, relwidth=1, relheight=1)
        self._browser_panel.lift()

        # Shift tkinter focus to root so the URL entry doesn't capture keystrokes
        self.root.focus_set()

        # Start WKWebView loading in background immediately (warm start)
        self.root.after(20, self._embed_wkwebview)
        # Begin polling loop after embed has had time to initialise
        self.root.after(600, self._wv_poll)

        # Slide in with ease-in-out cubic
        self._animate_browser(step=0, total_h=win_h, direction="in")

    def _close_browser(self):
        """Slide the browser panel out and remove the WKWebView."""
        if not self._browser_visible:
            return
        win_h = self.root.winfo_height()
        self._animate_browser(step=0, total_h=win_h, direction="out")

    def _animate_browser(self, step, total_h, direction):
        """Shared ease-in-out cubic animation for open and close."""
        STEPS = 48
        t = step / STEPS
        if t < 0.5:
            ease = 4.0 * t ** 3
        else:
            ease = 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0

        if direction == "in":
            y = int(-total_h * (1.0 - ease))     # -total_h → 0
        else:
            y = int(-total_h * ease)              # 0 → -total_h

        try:
            self._browser_panel.place(y=y)
        except Exception:
            return

        if step < STEPS:
            self.root.after(16, lambda: self._animate_browser(step + 1, total_h, direction))
        elif direction == "out":
            # Animation finished — tear down
            self._browser_panel.place_forget()
            self._browser_visible = False
            if self._wkwebview:
                try:
                    self._wkwebview.removeFromSuperview()
                except Exception:
                    pass
                self._wkwebview = None
            # Restore original window dimensions
            self.root.minsize(580, 600)
            self.root.resizable(False, True)
            self.root.geometry(f"{self._pre_browser_w}x{self.root.winfo_height()}")

    # ── WKWebView embedding ───────────────────────────────────────────────────

    def _embed_wkwebview(self):
        """Create a WKWebView and embed it as an NSView subview of this window.

        The view occupies the area below the nav bar.  It is a true part of the
        same NSWindow — not a separate process or window.
        """
        if not HAS_WKWEBVIEW or self._wkwebview is not None:
            return
        try:
            self._do_embed_wkwebview()
        except Exception as exc:
            self._log(f"[browser] WKWebView init error: {exc}", "muted")

    def _do_embed_wkwebview(self):
        from Foundation import NSURL, NSURLRequest

        # ── Find our NSWindow ─────────────────────────────────────────────────
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

        # ── Content-view dimensions in points ─────────────────────────────────
        bounds = cv.bounds()
        cv_w = bounds.size.width
        cv_h = bounds.size.height
        nav_h = self._browser_nav_h      # 59 px (nav 58 + divider 1)

        # NSView y=0 is at the bottom; webview fills from bottom up to below nav bar.
        wv_frame = NSMakeRect(0, 0, cv_w, cv_h - nav_h)

        # ── WKWebView configuration ───────────────────────────────────────────
        # No ObjC delegates or message handlers — they cause PyEval_RestoreThread
        # crashes in Python 3.14.  All signalling is done via URL polling instead.
        config = WKWebViewConfiguration.new()
        ctrl   = WKUserContentController.new()

        # Inject download-button JS at document end (static injection)
        script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            WEBVIEW_JS,
            1,      # WKUserScriptInjectionTimeAtDocumentEnd
            False,
        )
        ctrl.addUserScript_(script)
        config.setUserContentController_(ctrl)

        # ── Create and add WKWebView ─────────────────────────────────────────
        wv = WKWebView.alloc().initWithFrame_configuration_(wv_frame, config)

        # Chrome UA → YouTube serves full desktop layout (sidebar, recommendations)
        wv.setCustomUserAgent_(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        # No setNavigationDelegate_ — that's what caused the crash.
        # JS re-injection and URL-bar sync are handled by _wv_poll() instead.

        cv.addSubview_(wv)
        self._wkwebview = wv

        # Give the WKWebView exclusive keyboard focus so AppKit doesn't also
        # route keystrokes to the tkinter layer (which caused double-typing).
        nswin.makeFirstResponder_(wv)

        # Bind resize so WKWebView tracks window size
        self.root.bind("<Configure>", self._on_window_configure, add="+")

        # Load YouTube
        url = NSURL.URLWithString_("https://www.youtube.com")
        wv.loadRequest_(NSURLRequest.requestWithURL_(url))

    # ── WKWebView polling loop (replaces ObjC delegate callbacks) ────────────

    def _wv_poll(self):
        """Poll WKWebView.URL() every 300 ms — safe Python→ObjC; no GIL conflict.

        Detects the #__canopy_dl__:<encoded-url> hash set by the download button,
        clears it, and triggers the download.  Also keeps the URL bar in sync and
        periodically re-injects WEBVIEW_JS so SPA navigations always have the button.
        """
        if not self._wkwebview or not self._browser_visible:
            return
        try:
            url_obj = self._wkwebview.URL()
            if url_obj:
                url_str = str(url_obj.absoluteString())
                if '#__canopy_dl__:' in url_str:
                    # Download signal from JS button click
                    import urllib.parse
                    fragment = url_str.split('#__canopy_dl__:', 1)[1]
                    dl_url   = urllib.parse.unquote(fragment)
                    # Clear the hash so we don't re-trigger
                    self._wkwebview.evaluateJavaScript_completionHandler_(
                        "if(location.hash.startsWith('#__canopy_dl__:')){"
                        "(window.__cpwv_orig_replace||history.replaceState)"
                        ".call(history,null,'',location.pathname+location.search);}",
                        None,
                    )
                    _ALLOWED_PREFIXES = (
                        'https://www.youtube.com/',
                        'https://youtu.be/',
                        'https://youtube.com/',
                        'https://music.youtube.com/',
                    )
                    if any(dl_url.startswith(p) for p in _ALLOWED_PREFIXES):
                        self._browser_trigger_download(dl_url)
                    # else: silently ignore — non-YouTube page tried to inject a download
                elif url_str and url_str != 'about:blank':
                    if url_str != self._wv_last_url:
                        self._wv_last_url = url_str
                        self._on_wv_nav(url_str)
                        # URL changed — call updateDlBtn immediately (mirrors what
                        # _CanopyNavDelegate.webView_didFinishNavigation_ used to do)
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

        # Every ~6 s (20 × 300 ms) full re-injection as safety net.
        # Reset __cpwv first so the guard doesn't block the re-run.
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

    def _on_wv_nav(self, url):
        """Update URL bar when WKWebView navigates."""
        if self._browser_url_var:
            self._browser_url_var.set(url)

    # ── WKWebView nav bar actions ─────────────────────────────────────────────

    def _return_focus_to_wv(self):
        """Give keyboard focus back to WKWebView after URL entry loses focus."""
        if self._wkwebview and self._wv_nswin:
            try:
                self._wv_nswin.makeFirstResponder_(self._wkwebview)
            except Exception:
                pass

    def _wv_navigate(self, url=None):
        if not self._wkwebview:
            return
        from Foundation import NSURL, NSURLRequest
        target = (url or "").strip()
        if not target:
            return
        if target.startswith("file://"):
            return  # block local filesystem access via the nav bar
        if not target.startswith(("http://", "https://")):
            target = "https://" + target
        self._wkwebview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(target)))
        # Return keyboard focus to WKWebView after navigating
        self._return_focus_to_wv()

    def _wv_go_back(self):
        if self._wkwebview:
            self._wkwebview.goBack()

    def _wv_go_forward(self):
        if self._wkwebview:
            self._wkwebview.goForward()

    def _wv_reload(self):
        if self._wkwebview:
            self._wkwebview.reload_(None)

    def _on_window_configure(self, event):
        """Keep WKWebView frame in sync when the Canopy window resizes."""
        if self._wkwebview and self._wv_nswin:
            try:
                cv     = self._wv_nswin.contentView()
                bounds = cv.bounds()
                nav_h  = self._browser_nav_h
                self._wkwebview.setFrame_(
                    NSMakeRect(0, 0, bounds.size.width, bounds.size.height - nav_h)
                )
            except Exception:
                pass

    def _browser_trigger_download(self, url):
        """Called when the user clicks 'Download with Canopy' inside the browser."""
        self._close_browser()          # slide browser away so user sees the download UI
        self._current_url = url
        self._fetch_info()

    # ── Download picker dialog ────────────────────────────────────────────────

    def _show_download_picker(self):
        title    = self.info.get("title", "Unknown")
        uploader = self.info.get("uploader", "")
        duration = self.info.get("duration_string", "")
        video_id = self.info.get("id", "")

        DIALOG_W = 400
        THUMB_DH = 225

        dlg = ctk.CTkToplevel(self.root)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.configure(fg_color=CARD)
        dlg.transient(self.root)
        dlg.grab_set()

        thumb_bg = ctk.CTkFrame(dlg, fg_color="#c8e6d4", corner_radius=0,
                                  width=DIALOG_W, height=THUMB_DH)
        thumb_bg.pack(fill="x")
        thumb_bg.pack_propagate(False)

        thumb_lbl = ctk.CTkLabel(thumb_bg, text="▶",
                                  font=("Helvetica", 40),
                                  text_color=ACCENT,
                                  fg_color="transparent")
        thumb_lbl.pack(expand=True)
        dlg._photo = None

        def _load_thumb():
            cached = os.path.join(THUMB_CACHE, f"{video_id}.jpg") if video_id else ""
            if cached and os.path.exists(cached) and PILLOW:
                try:
                    img     = Image.open(cached).convert("RGB")
                    img     = img.resize((DIALOG_W, THUMB_DH), Image.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=img, size=(DIALOG_W, THUMB_DH))
                    def _apply():
                        if dlg.winfo_exists():
                            thumb_lbl.configure(image=ctk_img, text="")
                            thumb_bg.configure(fg_color="#1c1c1e")
                            dlg._photo = ctk_img
                    dlg.after(0, _apply)
                except Exception:
                    pass

        threading.Thread(target=_load_thumb, daemon=True).start()

        info_f = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=0)
        info_f.pack(fill="x", padx=20, pady=(16, 12))

        ctk.CTkLabel(info_f, text=title,
                     font=("Helvetica", 13, "bold"),
                     text_color=FG,
                     fg_color="transparent",
                     anchor="w", justify="left",
                     wraplength=360).pack(fill="x")

        detail = "  ·  ".join(p for p in (uploader, duration) if p)
        if detail:
            ctk.CTkLabel(info_f, text=detail,
                         font=("Helvetica", 10),
                         text_color=MUTED,
                         fg_color="transparent",
                         anchor="w").pack(fill="x", pady=(5, 0))

        ctk.CTkFrame(dlg, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

        # ── Completion preferences (small checkboxes) ─────────────────────────
        prefs_f = ctk.CTkFrame(dlg, fg_color=BG, corner_radius=0)
        prefs_f.pack(fill="x")

        prefs_inner = ctk.CTkFrame(prefs_f, fg_color="transparent", corner_radius=0)
        prefs_inner.pack(fill="x", padx=20, pady=(10, 10))

        _cb_kwargs = dict(
            font=("Helvetica", 11),
            text_color=MUTED,
            fg_color=ACCENT,
            hover_color="#3d6b4a",
            checkmark_color=CARD,
            border_color=BORDER,
            border_width_checked=0,
            corner_radius=4,
            checkbox_width=15,
            checkbox_height=15,
        )

        ctk.CTkCheckBox(prefs_inner,
                        text="Show in Finder when complete",
                        variable=self._opt_show_in_folder,
                        **_cb_kwargs).pack(anchor="w")

        ctk.CTkCheckBox(prefs_inner,
                        text="Open file when complete",
                        variable=self._opt_open_when_done,
                        **_cb_kwargs).pack(anchor="w", pady=(7, 0))

        ctk.CTkFrame(dlg, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

        options = [
            ("4K Ultra HD",  "mp4", "4K",    "▶", "2160p  ·  VP9 / HEVC  ·  MP4"),
            ("1080p HD",     "mp4", "1080p", "▶", "Best quality  ·  H.264  ·  MP4"),
            ("720p",         "mp4", "720p",  "▶", "High definition  ·  H.264  ·  MP4"),
            ("480p",         "mp4", "480p",  "▶", "Standard  ·  H.264  ·  MP4"),
            ("Audio — MP3",  "mp3", "Best",  "♪", "Audio only  ·  192 kbps  ·  MP3"),
        ]

        for opt_label, fmt, quality, icon, sub in options:
            def _pick(f=fmt, q=quality):
                dlg.destroy()
                self.format_var.set(f.upper())
                self.quality_var.set(q)
                self._begin_download(f, q)

            row = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=0, cursor="hand2")
            row.pack(fill="x")

            pad = ctk.CTkFrame(row, fg_color=CARD, corner_radius=0)
            pad.pack(fill="x", padx=20, pady=13)

            ctk.CTkLabel(pad, text=icon,
                         font=("Helvetica", 16),
                         text_color=ACCENT,
                         fg_color="transparent",
                         width=24).pack(side="left")

            col = ctk.CTkFrame(pad, fg_color=CARD, corner_radius=0)
            col.pack(side="left", padx=(12, 0), fill="x", expand=True)

            ctk.CTkLabel(col, text=opt_label,
                         font=("Helvetica", 13, "bold"),
                         text_color=FG,
                         fg_color="transparent",
                         anchor="w").pack(anchor="w")

            ctk.CTkLabel(col, text=sub,
                         font=("Helvetica", 10),
                         text_color=MUTED,
                         fg_color="transparent",
                         anchor="w").pack(anchor="w", pady=(2, 0))

            ctk.CTkLabel(pad, text="›",
                         font=("Helvetica", 20),
                         text_color=DIM,
                         fg_color="transparent").pack(side="right")

            ctk.CTkFrame(dlg, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")
            self._bind_picker_row(row, _pick)

        ctk.CTkButton(dlg, text="Cancel",
                      font=("Helvetica", 12),
                      fg_color=CARD,
                      hover_color="#f0ede8",
                      text_color=MUTED,
                      corner_radius=0,
                      height=48,
                      border_width=0,
                      command=dlg.destroy).pack(fill="x")

        dlg.update_idletasks()
        dh = dlg.winfo_reqheight()
        x  = self.root.winfo_x() + (self.root.winfo_width()  - DIALOG_W) // 2
        y  = self.root.winfo_y() + (self.root.winfo_height() - dh)        // 2
        dlg.geometry(f"{DIALOG_W}x{dh}+{x}+{y}")

    def _bind_picker_row(self, widget, cmd):
        widget.bind("<Button-1>", lambda e: cmd())
        widget.bind("<Enter>",    lambda e: self._row_bg(widget, BG))
        widget.bind("<Leave>",    lambda e: self._row_bg(widget, CARD))
        for child in widget.winfo_children():
            self._bind_picker_row(child, cmd)

    def _row_bg(self, widget, color):
        try:
            widget.configure(fg_color=color)
        except Exception:
            try:
                widget.configure(bg=color)
            except Exception:
                pass
        for child in widget.winfo_children():
            self._row_bg(child, color)

    def _begin_download(self, fmt, quality):
        if not self.info or self.is_downloading:
            return
        url      = self._current_url
        title    = self.info.get("title", "Unknown")
        video_id = self.info.get("id", "unknown")
        self.is_downloading      = True
        self._download_completed = False
        self._open_dl_log(video_id, title)
        self._hide_dl_footer()        # vanish once download is engaged
        self.dl_btn.configure(state="disabled")
        self.paste_btn.configure(state="disabled")
        self.act_bar.set(0)
        self.prog_detail.configure(text="")
        self.prog_pct.configure(text="")
        self._log(f"Starting {fmt.upper()} {quality} download...", "green")
        self._pill("Downloading")
        threading.Thread(target=self._do_download,
                         args=(url, fmt, quality), daemon=True).start()

    # ── Download logic (unchanged) ────────────────────────────────────────────

    def _do_download(self, url, fmt, quality):
        self._write_log(f"Download start  url={url}  fmt={fmt}  quality={quality}")
        self._write_log(f"Save path: {self.download_path}")
        self._write_log(f"ffmpeg: {FFMPEG_PATH or 'NOT FOUND'}")
        self._last_filename = None

        try:
            if fmt == "mp3":
                ydl_fmt = "bestaudio/best"
                postprocessors = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3",
                                   "preferredquality": "192"}]
            elif fmt == "m4a":
                ydl_fmt = "bestaudio[ext=m4a]/bestaudio/best"
                postprocessors = []
            else:
                h_map = {"4K": 2160, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
                if fmt == "mp4":
                    if quality == "4K":
                        # 4K on YouTube is typically VP9/AV1; prefer those, fall back to any
                        ydl_fmt = (
                            "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]"
                            "/bestvideo[height<=2160]+bestaudio/best"
                        )
                    elif quality in h_map:
                        h = h_map[quality]
                        ydl_fmt = (
                            f"bestvideo[vcodec^=avc1][height<={h}][ext=mp4]"
                            f"+bestaudio[ext=m4a]"
                            f"/bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
                            f"/bestvideo[height<={h}]+bestaudio/best"
                        )
                    else:
                        ydl_fmt = (
                            "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]"
                            "/bestvideo[ext=mp4]+bestaudio[ext=m4a]"
                            "/bestvideo+bestaudio/best"
                        )
                elif quality in h_map:
                    h = h_map[quality]
                    ydl_fmt = (f"bestvideo[height<={h}][ext={fmt}]+bestaudio"
                               f"/bestvideo[height<={h}]+bestaudio/best")
                else:
                    ydl_fmt = (f"bestvideo[ext={fmt}]+bestaudio"
                               f"/bestvideo+bestaudio/best")
                postprocessors = []

            outtmpl = os.path.join(self.download_path, "%(title)s.%(ext)s")
            self._write_log(f"Format string: {ydl_fmt}")
            self._write_log(f"outtmpl: {outtmpl}")

            ydl_opts = {
                "format": ydl_fmt,
                "outtmpl": outtmpl,
                "merge_output_format": fmt if fmt not in ("mp3", "m4a") else None,
                "progress_hooks": [self._progress_hook],
                "postprocessor_hooks": [self._postprocessor_hook],
                "logger": YtdlLogger(self._write_log),
                "quiet": False,
                "no_warnings": False,
                "restrictfilenames": True,   # prevent path traversal via video title
            }
            if FFMPEG_PATH:
                ydl_opts["ffmpeg_location"] = os.path.dirname(FFMPEG_PATH)
            if postprocessors:
                ydl_opts["postprocessors"] = postprocessors

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            if self._last_filename and not os.path.isfile(self._last_filename):
                swapped = os.path.splitext(self._last_filename)[0] + f".{fmt}"
                if os.path.isfile(swapped):
                    self._write_log(f"Resolved via extension swap: {swapped}")
                    self._last_filename = swapped

            if self._last_filename:
                exists = os.path.isfile(self._last_filename)
                self._write_log(f"Final file: {self._last_filename}  exists={exists}")
            else:
                self._write_log("WARNING: no filename captured")

            entry = {
                "title":         self.info.get("title", "Unknown"),
                "url":           url,
                "thumbnail_url": self.info.get("thumbnail", ""),
                "video_id":      self.info.get("id", ""),
                "uploader":      self.info.get("uploader", ""),
                "duration":      self.info.get("duration_string", ""),
                "format":        fmt,
                "quality":       quality,
                "save_path":     self.download_path,
                "file_path":     self._last_filename or "",
                "log_path":      self._dl_log_path or "",
                "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            self.history.insert(0, entry)
            self.history = self.history[:50]
            self._save_history()

            thumb_url = entry["thumbnail_url"]
            video_id  = entry["video_id"]
            if thumb_url and video_id:
                threading.Thread(target=self._fetch_thumb,
                                 args=(thumb_url, video_id), daemon=True).start()

            self._ui(self._on_download_done)
        except Exception as e:
            self._write_log(f"Download exception: {e}")
            self._ui(lambda msg=str(e): self._on_download_error(msg))

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            speed_bps  = d.get("speed")   # raw float bytes/sec — no ANSI codes
            eta_sec    = d.get("eta")     # raw int seconds remaining

            pct = (downloaded / total * 100) if total > 0 else 0

            # Chrome-style: "1.1 GB of 2.6 GB  ·  5.1 MB/s  ·  12 min 3 sec left"
            parts = []
            if total > 0:
                parts.append(f"{_fmt_bytes(downloaded)} of {_fmt_bytes(total)}")
            if speed_bps and speed_bps > 0:
                parts.append(_fmt_speed(speed_bps))
            if eta_sec is not None and eta_sec >= 0:
                parts.append(f"{_fmt_eta(eta_sec)} left")

            detail  = "  ·  ".join(parts)
            pct_str = f"{pct:.0f}%"
            self._ui(lambda p=pct, s=detail, ps=pct_str:
                     self._set_progress(p, s, ps))

        elif d["status"] == "finished":
            fname = d.get("filename", "")
            if fname:
                self._last_filename = fname
                self._write_log(f"Fragment finished: {fname}")
            self._ui(lambda: self._set_progress(95, "Merging tracks…", ""))

    def _postprocessor_hook(self, d):
        if d.get("status") == "finished":
            info = d.get("info_dict", {})
            fp   = info.get("filepath") or info.get("filename", "")
            if fp and os.path.isfile(fp):
                self._last_filename = fp
                self._write_log(f"Post-process output: {fp}")

    def _set_progress(self, pct, detail, pct_str=None):
        self.act_bar.set(pct / 100)
        self.prog_detail.configure(text=detail)
        if pct_str is not None:
            self.prog_pct.configure(text=pct_str)
        self._log_update(f"Downloading  {detail}", "active")

    def _on_download_done(self):
        if self._download_completed:
            return
        self._download_completed = True
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
        self._refresh_history()

        # ── Completion actions based on picker preferences ──────────────────
        fp = self._last_filename if (self._last_filename and
                                      os.path.isfile(self._last_filename)) else None
        if self._opt_open_when_done.get() and fp:
            try:
                subprocess.Popen(["open", fp])
            except Exception:
                pass
        if self._opt_show_in_folder.get():
            try:
                target = fp if fp else self.download_path
                # "-R" reveals the file; without a file, just open the folder
                cmd = ["open", "-R", target] if fp else ["open", target]
                subprocess.Popen(cmd)
            except Exception:
                pass

    def _on_download_error(self, error):
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

    def _fetch_thumb(self, thumb_url, video_id):
        path = os.path.join(THUMB_CACHE, f"{video_id}.jpg")
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

    def _load_thumb(self, video_id, w=HIST_TW, h=HIST_TH):
        if not PILLOW:
            return None
        path = os.path.join(THUMB_CACHE, f"{video_id}.jpg")
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

    def _refresh_history(self):
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

    def _render_row(self, entry):
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
                     text_color="#cc3333" if (file_path and not file_exists) else MUTED,
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

    def _show_row_menu(self, btn, entry):
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

    def _delete_file(self, entry):
        file_path = entry.get("file_path", "")
        if not file_path or not os.path.isfile(file_path):
            messagebox.showwarning("File Not Found",
                                   "The file could not be found on disk.")
            return
        if messagebox.askyesno("Delete File",
                               f'Permanently delete:\n"{os.path.basename(file_path)}"'
                               f'\n\nThis cannot be undone.'):
            try:
                os.remove(file_path)
                entry["file_path"] = ""
                self._save_history()
                self._refresh_history()
            except Exception as e:
                messagebox.showerror("Delete Failed", str(e))

    def _delete_from_history(self, entry):
        title = entry.get("title", "this item")
        if messagebox.askyesno("Delete from History",
                               f'Remove "{title[:60]}" from history?\n\n'
                               f'The downloaded file will not be deleted.'):
            try:
                self.history.remove(entry)
            except ValueError:
                pass
            self._save_history()
            self._refresh_history()

    def _delete_both(self, entry):
        file_path = entry.get("file_path", "")
        if not file_path or not os.path.isfile(file_path):
            messagebox.showwarning("File Not Found",
                                   "The file could not be found on disk.")
            return
        if messagebox.askyesno("Delete Both",
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
            self._save_history()
            self._refresh_history()

    # ── About panel ───────────────────────────────────────────────────────────

    def _show_about(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.configure(fg_color=CARD)
        dlg.transient(self.root)
        dlg.grab_set()

        W = 320
        content = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=0)
        content.pack(fill="x", padx=32, pady=(32, 28))

        # Logo mark at 64 pt
        mark_img = _load_brand_mark(64)
        if mark_img:
            self._about_mark_ref = mark_img
            ctk.CTkLabel(content, image=mark_img, text="",
                         fg_color="transparent").pack()

        ctk.CTkLabel(content, text="C A N O P Y",
                     font=("Helvetica Neue", 15),
                     text_color=FG,
                     fg_color="transparent").pack(pady=(14, 4))

        ctk.CTkLabel(content, text="YouTube Downloader for creators",
                     font=("Helvetica", 11),
                     text_color=MUTED,
                     fg_color="transparent").pack()

        ctk.CTkFrame(content, fg_color=BORDER, height=1,
                     corner_radius=0).pack(fill="x", pady=(20, 16))

        ctk.CTkLabel(content, text="Built with yt-dlp · CustomTkinter · pywebview",
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

    def _short_path(self, path):
        home = os.path.expanduser("~")
        return ("~" + path[len(home):]) if path.startswith(home) else path


def main():
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")

    root = ctk.CTk()
    CanopyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
