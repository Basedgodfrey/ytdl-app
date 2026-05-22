import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import threading
import multiprocessing
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

try:
    import webview
    WEBVIEW = True
except ImportError:
    WEBVIEW = False


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
THUMB_W, THUMB_H = 88, 56
HIST_TW,  HIST_TH  = 68, 44

# ── Browser JS injected into every page ──────────────────────────────────────
# Adds a nav bar + floating "Download with Canopy" button on video pages.

BROWSER_JS = r"""
(function () {
    'use strict';
    if (window.__canopy_init) return;
    window.__canopy_init = true;

    var ACCENT  = '#4a7c59';
    var TITLEBAR = '#eeeae2';
    var BORDER  = '#dedad3';
    var NAV_H   = 46;

    /* ── NAV BAR ── */
    function buildNav() {
        var old = document.getElementById('__cpnav');
        if (old) old.remove();

        var nav = document.createElement('div');
        nav.id = '__cpnav';
        nav.style.cssText =
            'position:fixed;top:0;left:0;right:0;height:' + NAV_H + 'px;' +
            'background:' + TITLEBAR + ';border-bottom:1px solid ' + BORDER + ';' +
            'display:flex;align-items:center;gap:6px;padding:0 14px;' +
            'z-index:2147483647;box-shadow:0 1px 6px rgba(0,0,0,.08);' +
            'font-family:-apple-system,BlinkMacSystemFont,sans-serif;';

        function mkBtn(label, title, fn) {
            var b = document.createElement('button');
            b.textContent = label;
            b.title = title;
            b.style.cssText =
                'background:none;border:none;font-size:18px;cursor:pointer;' +
                'color:#6b6560;padding:4px 8px;border-radius:6px;line-height:1;' +
                'flex-shrink:0;';
            b.onmouseenter = function () { b.style.background = BORDER; };
            b.onmouseleave = function () { b.style.background = 'none'; };
            b.onclick = fn;
            return b;
        }

        var backBtn   = mkBtn('‹', 'Back',    function () { history.back(); });
        var fwdBtn    = mkBtn('›', 'Forward', function () { history.forward(); });
        var reloadBtn = mkBtn('↺', 'Reload',  function () { location.reload(); });

        var urlInput = document.createElement('input');
        urlInput.id = '__cpurl';
        urlInput.type = 'text';
        urlInput.value = location.href;
        urlInput.spellcheck = false;
        urlInput.style.cssText =
            'flex:1;height:28px;border-radius:8px;border:1px solid ' + BORDER + ';' +
            'padding:0 10px;font-size:12px;background:#fff;color:#2a2520;outline:none;' +
            'min-width:0;';
        urlInput.addEventListener('focus', function () { urlInput.select(); });
        urlInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') goUrl();
        });

        function goUrl() {
            var url = urlInput.value.trim();
            if (!url) return;
            if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
            location.href = url;
        }

        var goBtn = mkBtn('→', 'Go', goUrl);

        nav.appendChild(backBtn);
        nav.appendChild(fwdBtn);
        nav.appendChild(reloadBtn);
        nav.appendChild(urlInput);
        nav.appendChild(goBtn);
        document.documentElement.insertBefore(nav, document.documentElement.firstChild);
    }

    /* ── DOWNLOAD BUTTON ── */
    function updateDlBtn() {
        var url     = location.href;
        var isVideo = /[?&]v=/.test(url);
        var dlBtn   = document.getElementById('__cpdl');

        if (isVideo && !dlBtn) {
            dlBtn = document.createElement('div');
            dlBtn.id = '__cpdl';
            dlBtn.innerHTML = '⬇︎ &nbsp;Download with Canopy';
            dlBtn.style.cssText =
                'position:fixed;bottom:28px;right:28px;' +
                'background:' + ACCENT + ';color:#fff;' +
                'font-family:-apple-system,BlinkMacSystemFont,sans-serif;' +
                'font-size:13px;font-weight:600;' +
                'padding:11px 22px;border-radius:50px;cursor:pointer;' +
                'z-index:2147483647;user-select:none;' +
                'box-shadow:0 4px 18px rgba(74,124,89,.45);' +
                'transition:transform .15s,box-shadow .15s;';
            dlBtn.onmouseenter = function () {
                dlBtn.style.transform   = 'scale(1.05)';
                dlBtn.style.boxShadow   = '0 6px 24px rgba(74,124,89,.6)';
            };
            dlBtn.onmouseleave = function () {
                dlBtn.style.transform   = '';
                dlBtn.style.boxShadow   = '0 4px 18px rgba(74,124,89,.45)';
            };
            dlBtn.onclick = function () {
                if (window.pywebview && window.pywebview.api) {
                    window.pywebview.api.download_url(location.href);
                    dlBtn.innerHTML = '✓ &nbsp;Sent to Canopy';
                    dlBtn.style.background = '#3b6d45';
                    setTimeout(function () {
                        dlBtn.innerHTML = '⬇︎ &nbsp;Download with Canopy';
                        dlBtn.style.background = ACCENT;
                    }, 2000);
                }
            };
            document.body.appendChild(dlBtn);
        } else if (!isVideo && dlBtn) {
            dlBtn.remove();
        }

        /* sync url bar */
        var inp = document.getElementById('__cpurl');
        if (inp && document.activeElement !== inp) inp.value = location.href;
    }

    /* ── SPA NAVIGATION INTERCEPTION ── */
    var _push = history.pushState.bind(history);
    history.pushState = function () {
        _push.apply(this, arguments);
        setTimeout(updateDlBtn, 800);
    };
    var _replace = history.replaceState.bind(history);
    history.replaceState = function () {
        _replace.apply(this, arguments);
        setTimeout(updateDlBtn, 800);
    };
    window.addEventListener('popstate', function () { setTimeout(updateDlBtn, 400); });

    /* ── INIT ── */
    buildNav();
    setTimeout(updateDlBtn, 1200);
    setTimeout(function () {
        if (document.body) {
            var cur = parseInt(document.body.style.paddingTop) || 0;
            if (cur < NAV_H) document.body.style.paddingTop = NAV_H + 'px';
        }
    }, 400);
})();
"""


# ── Browser process (runs in separate process — macOS WKWebView needs main thread) ──

def _run_browser_process(event_queue, initial_url):
    """Entry point for the browser subprocess."""
    try:
        import webview as wv
    except ImportError:
        return

    class BrowserAPI:
        def download_url(self, url):
            event_queue.put(url)

    win = wv.create_window(
        title="Canopy Browser",
        url=initial_url,
        js_api=BrowserAPI(),
        width=1140,
        height=780,
        background_color="#f5f3ee",
        text_select=True,
        zoomable=True,
    )

    def on_loaded():
        try:
            win.evaluate_js(BROWSER_JS)
        except Exception:
            pass

    win.events.loaded += on_loaded
    wv.start(debug=False)


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
        self.root.title("Canopy")
        self.root.geometry("580x860")
        self.root.minsize(580, 600)
        self.root.resizable(False, True)
        self.root.configure(fg_color=BG)

        self.download_path         = os.path.expanduser("~/Downloads")
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

        # Browser subprocess state
        self._browser_proc  = None
        self._browser_queue = None

        self.format_var  = tk.StringVar(value="MP4")
        self.quality_var = tk.StringVar(value="Best")

        self.history = self._load_history()
        os.makedirs(THUMB_CACHE, exist_ok=True)
        os.makedirs(DL_LOGS_DIR, exist_ok=True)
        self._setup_log()
        _set_dock_icon()
        self._build_ui()
        self._refresh_history()

    # ── Logging ──────────────────────────────────────────────────────────────

    def _setup_log(self):
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

        # "Browse" button — left side (only shown if pywebview is available)
        if WEBVIEW:
            browse_lnk = ctk.CTkLabel(tbar, text="Browse",
                                       font=("Helvetica", 12, "bold"),
                                       text_color=ACCENT,
                                       fg_color="transparent",
                                       cursor="hand2")
            browse_lnk.place(relx=0.0, rely=0.5, anchor="w", x=PAD)
            browse_lnk.bind("<Button-1>", lambda e: self._open_browser())

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

        # Body
        body = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        body.pack(fill="x")

        inner = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        inner.pack(fill="x", padx=PAD, pady=(20, 0))

        ctk.CTkLabel(inner, text="VIDEO URL",
                     font=("Helvetica", 9, "bold"),
                     text_color=MUTED,
                     fg_color="transparent",
                     anchor="w").pack(fill="x", pady=(0, 6))

        # URL card
        url_card = ctk.CTkFrame(inner, fg_color=CARD,
                                 corner_radius=14,
                                 border_color=BORDER, border_width=1)
        url_card.pack(fill="x", pady=(0, 10))

        url_row = ctk.CTkFrame(url_card, fg_color=CARD, corner_radius=0)
        url_row.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(url_row, text="⌁",
                     font=("Helvetica", 16),
                     text_color=DIM,
                     fg_color="transparent").pack(side="left")

        self.url_entry = ctk.CTkEntry(url_row,
                                       placeholder_text="Paste a YouTube URL...",
                                       font=("Helvetica", 13),
                                       fg_color=CARD,
                                       text_color=FG,
                                       placeholder_text_color=DIM,
                                       border_width=0,
                                       corner_radius=8)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.url_entry.bind("<Return>", lambda e: self._fetch_info())

        self.fetch_btn = ctk.CTkButton(url_row, text="Fetch",
                                        font=("Helvetica", 12, "bold"),
                                        fg_color=ACCENT,
                                        hover_color="#3d6b4a",
                                        text_color="#ffffff",
                                        corner_radius=10,
                                        width=72, height=34,
                                        command=self._fetch_info)
        self.fetch_btn.pack(side="left", padx=(10, 0))

        # Video info card
        self.video_card = ctk.CTkFrame(inner, fg_color=CARD,
                                        corner_radius=14,
                                        border_color=BORDER, border_width=1)
        self.video_card.pack(fill="x", pady=(0, 10))

        vc_inner = ctk.CTkFrame(self.video_card, fg_color=CARD, corner_radius=0)
        vc_inner.pack(fill="x", padx=14, pady=12)

        self.vc_thumb_box = ctk.CTkFrame(vc_inner, fg_color="#c8e6d4",
                                          corner_radius=10,
                                          width=THUMB_W, height=THUMB_H)
        self.vc_thumb_box.pack(side="left")
        self.vc_thumb_box.pack_propagate(False)

        self.vc_thumb_lbl = ctk.CTkLabel(self.vc_thumb_box, text="▶",
                                          font=("Helvetica", 18),
                                          text_color=ACCENT,
                                          fg_color="transparent")
        self.vc_thumb_lbl.pack(expand=True)
        self._vc_photo = None

        vc_info = ctk.CTkFrame(vc_inner, fg_color=CARD, corner_radius=0)
        vc_info.pack(side="left", fill="x", expand=True, padx=(12, 0))

        self.vc_title = ctk.CTkLabel(vc_info,
                                      text="Paste a YouTube URL to get started",
                                      font=("Helvetica", 12, "bold"),
                                      text_color=MUTED,
                                      fg_color="transparent",
                                      anchor="w", justify="left",
                                      wraplength=340)
        self.vc_title.pack(fill="x")

        self.vc_meta = ctk.CTkLabel(vc_info, text="",
                                     font=("Helvetica", 10),
                                     text_color=MUTED,
                                     fg_color="transparent",
                                     anchor="w")
        self.vc_meta.pack(fill="x", pady=(3, 0))

        pill_row = ctk.CTkFrame(vc_info, fg_color=CARD, corner_radius=0)
        pill_row.pack(fill="x", pady=(7, 0))

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
                                           ["Best", "1080p", "720p", "480p", "360p"])
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

        save_card.bind("<Button-1>", _pick_click)
        for w in save_card.winfo_children():
            w.bind("<Button-1>", _pick_click)

        self.format_var.trace_add("write",  lambda *_: self._sync_pills())
        self.quality_var.trace_add("write", lambda *_: self._sync_pills())

        # Progress card
        self._build_progress_card(inner)

        # Download button
        self.dl_btn = ctk.CTkButton(inner, text="Download",
                                     font=("Helvetica", 15, "bold"),
                                     fg_color=ACCENT,
                                     hover_color="#3d6b4a",
                                     text_color="#ffffff",
                                     corner_radius=14,
                                     height=50,
                                     state="disabled",
                                     command=self._start_download)
        self.dl_btn.pack(fill="x", pady=(0, 20))

        ctk.CTkFrame(self.root, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

        self._build_history_section(PAD)

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
        pc.pack(fill="x", padx=14, pady=(12, 8))

        status_row = ctk.CTkFrame(pc, fg_color=CARD, corner_radius=0)
        status_row.pack(fill="x")

        self.prog_status = ctk.CTkLabel(status_row, text="Ready",
                                         font=("Helvetica", 12, "bold"),
                                         text_color=ACCENT,
                                         fg_color="transparent",
                                         anchor="w")
        self.prog_status.pack(side="left")

        self.prog_detail = ctk.CTkLabel(status_row, text="",
                                         font=("Helvetica", 10),
                                         text_color=MUTED,
                                         fg_color="transparent",
                                         anchor="e")
        self.prog_detail.pack(side="right")

        self.act_bar = ctk.CTkProgressBar(pc,
                                           fg_color=PROG_TRK,
                                           progress_color=ACCENT,
                                           corner_radius=99,
                                           height=5)
        self.act_bar.set(0)
        self.act_bar.pack(fill="x", pady=(8, 0))

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

    def _fetch_info(self):
        url = self.url_entry.get().strip()
        if not url or self.is_fetching or self.is_downloading:
            return
        self.is_fetching = True
        self.fetch_btn.configure(state="disabled")
        self.dl_btn.configure(state="disabled")
        self.vc_title.configure(text="Fetching video info...", text_color=MUTED)
        self.vc_meta.configure(text="")
        self._log_clear()
        self._log(f"Fetching: {url[:60]}", "green")
        self._pill("Fetching")
        self.act_bar.set(0)
        self.prog_detail.configure(text="")
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
            self.root.after(0, lambda: self._on_fetch_done(
                title, meta, thumb_url, video_id, True))
        except Exception as e:
            self._write_log(f"Fetch error: {e}")
            self.root.after(0, lambda: self._on_fetch_done(str(e), "", "", "", False))

    def _on_fetch_done(self, title, meta, thumb_url, video_id, success):
        self.is_fetching = False
        self.fetch_btn.configure(state="normal")
        if success:
            self.vc_title.configure(text=title, text_color=FG)
            self.vc_meta.configure(text=meta)
            self.dl_btn.configure(state="normal")
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
                img     = Image.open(cached).convert("RGB")
                img     = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, size=(THUMB_W, THUMB_H))
                def _apply():
                    self._vc_photo = ctk_img
                    self.vc_thumb_lbl.configure(image=ctk_img, text="")
                    self.vc_thumb_box.configure(fg_color="#1c1c1e")
                self.root.after(0, _apply)
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

    def _open_browser(self):
        """Launch the browser subprocess (or bring it to front if already open)."""
        if self._browser_proc and self._browser_proc.is_alive():
            # Already open — nothing to do; OS will handle focus
            return

        self._browser_queue = multiprocessing.Queue()
        self._browser_proc  = multiprocessing.Process(
            target=_run_browser_process,
            args=(self._browser_queue, "https://www.youtube.com"),
            daemon=True,
        )
        self._browser_proc.start()

        # Poll for download events in a background thread
        def _poll():
            while self._browser_proc and self._browser_proc.is_alive():
                try:
                    url = self._browser_queue.get(timeout=0.5)
                    self.root.after(0, lambda u=url: self._browser_trigger_download(u))
                except Exception:
                    pass  # queue.Empty on timeout — keep looping

        threading.Thread(target=_poll, daemon=True).start()

    def _browser_trigger_download(self, url):
        """Called when the user clicks 'Download with Canopy' in the browser."""
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        # Bring Canopy to front
        self.root.lift()
        self.root.focus_force()
        # Auto-fetch
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

        options = [
            ("1080p HD",    "mp4", "1080p", "▶", "Best quality  ·  H.264  ·  MP4"),
            ("720p",        "mp4", "720p",  "▶", "High definition  ·  H.264  ·  MP4"),
            ("480p",        "mp4", "480p",  "▶", "Standard  ·  H.264  ·  MP4"),
            ("Audio — MP3", "mp3", "Best",  "♪", "Audio only  ·  192 kbps  ·  MP3"),
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
        url      = self.url_entry.get().strip()
        title    = self.info.get("title", "Unknown")
        video_id = self.info.get("id", "unknown")
        self.is_downloading      = True
        self._download_completed = False
        self._open_dl_log(video_id, title)
        self.dl_btn.configure(state="disabled")
        self.fetch_btn.configure(state="disabled")
        self.act_bar.set(0)
        self.prog_detail.configure(text="")
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
                h_map = {"1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
                if fmt == "mp4":
                    if quality in h_map:
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

            self.root.after(0, self._on_download_done)
        except Exception as e:
            self._write_log(f"Download exception: {e}")
            self.root.after(0, lambda: self._on_download_error(str(e)))

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            speed      = d.get("_speed_str", "").strip()
            eta        = d.get("_eta_str", "").strip()
            pct        = (downloaded / total * 100) if total > 0 else 0
            parts      = [f"{pct:.0f}%"]
            if speed: parts.append(speed)
            if eta:   parts.append(f"ETA {eta}")
            detail = "  ·  ".join(parts)
            self.root.after(0, lambda p=pct, s=detail: self._set_progress(p, s))
        elif d["status"] == "finished":
            fname = d.get("filename", "")
            if fname:
                self._last_filename = fname
                self._write_log(f"Fragment finished: {fname}")
            self.root.after(0, lambda: self._set_progress(95, "Processing..."))

    def _postprocessor_hook(self, d):
        if d.get("status") == "finished":
            info = d.get("info_dict", {})
            fp   = info.get("filepath") or info.get("filename", "")
            if fp and os.path.isfile(fp):
                self._last_filename = fp
                self._write_log(f"Post-process output: {fp}")

    def _set_progress(self, pct, detail):
        self.act_bar.set(pct / 100)
        self.prog_detail.configure(text=detail)
        self._log_update(f"Downloading  {detail}", "active")

    def _on_download_done(self):
        if self._download_completed:
            return
        self._download_completed = True
        self.is_downloading = False
        self.act_bar.set(1.0)
        self.prog_detail.configure(text="")
        self._write_log(f"Download complete. Folder: {self.download_path}")
        self._close_dl_log()
        self._log_update("Download complete!", "success")
        self._log(f"Saved to {self._short_path(self.download_path)}", "dim")
        self._pill("Done")
        self.dl_btn.configure(state="normal")
        self.fetch_btn.configure(state="normal")
        self._refresh_history()

    def _on_download_error(self, error):
        self.is_downloading = False
        self._write_log(f"Download failed: {error}")
        self._close_dl_log()
        self._log_update(f"Failed: {error[:80]}", "error")
        self._pill("Error")
        self.dl_btn.configure(state="normal")
        self.fetch_btn.configure(state="normal")
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
        self.root.after(0, self._refresh_history)

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
    # Required for PyInstaller + multiprocessing on macOS
    multiprocessing.freeze_support()

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")

    root = ctk.CTk()
    CanopyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
