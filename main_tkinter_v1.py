import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import yt_dlp
import os
import sys
import json
import urllib.request
import datetime
import webbrowser

try:
    from PIL import Image, ImageTk
    PILLOW = True
except ImportError:
    PILLOW = False

HISTORY_FILE = os.path.expanduser("~/.ytdl_history.json")
THUMB_CACHE  = os.path.expanduser("~/.ytdl_cache/thumbnails")
LOG_FILE     = os.path.expanduser("~/.ytdl_debug.log")
DL_LOGS_DIR  = os.path.expanduser("~/.ytdl_cache/logs")

# ── Canopy palette ─────────────────────────────────────────────────────────
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

FONT_H    = ("Helvetica", 16, "bold")
FONT_MED  = ("Helvetica", 14, "bold")
FONT      = ("Helvetica", 13)
FONT_SM   = ("Helvetica", 12)
FONT_XS   = ("Helvetica", 10)
FONT_PILL = ("Helvetica", 10, "bold")
FONT_MONO = ("Menlo", 10)

THUMB_W, THUMB_H = 88, 56   # video card thumbnail
HIST_TW, HIST_TH = 68, 44   # history row thumbnail


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
        self.root.geometry("580x820")
        self.root.minsize(580, 600)
        self.root.resizable(False, True)
        self.root.configure(bg=BG)

        self.download_path       = os.path.expanduser("~/Downloads")
        self.info                = None
        self.is_fetching         = False
        self.is_downloading      = False
        self.activity_open       = True
        self._thumb_refs         = {}
        self._dl_log_handle      = None
        self._dl_log_path        = None
        self._last_log_replaceable = False
        self._download_completed = False

        self.format_var  = tk.StringVar(value="MP4")
        self.quality_var = tk.StringVar(value="Best")

        self.history = self._load_history()
        os.makedirs(THUMB_CACHE, exist_ok=True)
        os.makedirs(DL_LOGS_DIR, exist_ok=True)
        self._setup_log()
        self._build_ui()
        self._refresh_history()

    # ── Logging ────────────────────────────────────────────────────────────

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
                f"Canopy — Process Log\n"
                f"{'=' * 50}\n"
                f"Date:    {now}\n"
                f"Video:   {title}\n"
                f"ID:      {video_id}\n"
                f"ffmpeg:  {FFMPEG_PATH or 'NOT FOUND'}\n"
                f"{'=' * 50}\n\n"
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

    # ── Persistence ────────────────────────────────────────────────────────

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

    # ── UI build ───────────────────────────────────────────────────────────

    def _build_ui(self):
        PAD = 22

        # ── Title bar ──────────────────────────────────────────────────────
        tbar = tk.Frame(self.root, bg=TITLEBAR, height=44)
        tbar.pack(fill="x")
        tbar.pack_propagate(False)

        tk.Label(tbar, text="Canopy", font=("Helvetica", 13, "bold"),
                 bg=TITLEBAR, fg="#6b6560").place(relx=0.5, rely=0.5, anchor="center")

        hist_lnk = tk.Label(tbar, text="History", font=("Helvetica", 12, "bold"),
                             bg=TITLEBAR, fg=ACCENT, cursor="hand2")
        hist_lnk.place(relx=1.0, rely=0.5, anchor="e", x=-PAD)
        hist_lnk.bind("<Button-1>", lambda e: self.hist_canvas.yview_moveto(1.0))

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        # ── Body ───────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        inner = tk.Frame(body, bg=BG)
        inner.pack(fill="x", padx=PAD, pady=(20, 0))

        # ── Section label ──────────────────────────────────────────────────
        tk.Label(inner, text="VIDEO URL", font=("Helvetica", 9, "bold"),
                 bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 6))

        # ── URL card ───────────────────────────────────────────────────────
        url_card = tk.Frame(inner, bg=CARD,
                            highlightbackground=BORDER, highlightthickness=1)
        url_card.pack(fill="x", pady=(0, 10))

        url_row = tk.Frame(url_card, bg=CARD)
        url_row.pack(fill="x", padx=14, pady=12)

        tk.Label(url_row, text="⌁", font=("Helvetica", 16),
                 bg=CARD, fg=DIM).pack(side="left")

        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(url_row, textvariable=self.url_var,
                                  font=FONT, bg=CARD, fg=FG,
                                  insertbackground=FG, relief="flat", bd=0,
                                  highlightthickness=0)
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=2, padx=(8, 0))
        self.url_entry.bind("<Return>", lambda e: self._fetch_info())

        self.fetch_btn = tk.Button(url_row, text="Fetch",
                                   font=("Helvetica", 12, "bold"),
                                   bg=ACCENT, fg="#fff", relief="flat", bd=0,
                                   activebackground="#3d6b4a",
                                   activeforeground="#fff",
                                   cursor="hand2",
                                   command=self._fetch_info)
        self.fetch_btn.pack(side="left", padx=(10, 0), ipady=6, ipadx=14)

        # ── Video info card ────────────────────────────────────────────────
        self.video_card = tk.Frame(inner, bg=CARD,
                                   highlightbackground=BORDER, highlightthickness=1)
        self.video_card.pack(fill="x", pady=(0, 10))

        vc_inner = tk.Frame(self.video_card, bg=CARD)
        vc_inner.pack(fill="x", padx=14, pady=12)

        # Thumbnail
        self.vc_thumb_box = tk.Frame(vc_inner, bg="#c8e6d4",
                                     width=THUMB_W, height=THUMB_H)
        self.vc_thumb_box.pack(side="left")
        self.vc_thumb_box.pack_propagate(False)
        self.vc_thumb_lbl = tk.Label(self.vc_thumb_box, text="▶",
                                     font=("Helvetica", 18),
                                     bg="#c8e6d4", fg="#4a7c59")
        self.vc_thumb_lbl.pack(expand=True)
        self._vc_photo = None

        # Info
        vc_info = tk.Frame(vc_inner, bg=CARD)
        vc_info.pack(side="left", fill="x", expand=True, padx=(12, 0))

        self.vc_title = tk.Label(vc_info, text="Paste a YouTube URL to get started",
                                 font=("Helvetica", 12, "bold"),
                                 bg=CARD, fg=MUTED, anchor="w",
                                 wraplength=340, justify="left")
        self.vc_title.pack(fill="x")

        self.vc_meta = tk.Label(vc_info, text="",
                                font=FONT_XS, bg=CARD, fg=MUTED, anchor="w")
        self.vc_meta.pack(fill="x", pady=(3, 0))

        pill_row = tk.Frame(vc_info, bg=CARD)
        pill_row.pack(fill="x", pady=(7, 0))
        self.vc_fmt_pill  = tk.Label(pill_row, text="MP4",
                                     font=FONT_PILL, bg=PILL_BG, fg=PILL_FG,
                                     padx=8, pady=2)
        self.vc_fmt_pill.pack(side="left")
        self.vc_qual_pill = tk.Label(pill_row, text="Best",
                                     font=FONT_PILL, bg="#e8ede6", fg="#5a7060",
                                     padx=8, pady=2)
        self.vc_qual_pill.pack(side="left", padx=(6, 0))

        # ── Options row ────────────────────────────────────────────────────
        opts_row = tk.Frame(inner, bg=BG)
        opts_row.pack(fill="x", pady=(0, 10))

        self._opt_fmt  = self._option_card(opts_row, "FORMAT",  self.format_var,
                                           ["MP4", "MP3", "M4A", "WEBM"])
        self._opt_fmt.pack(side="left", fill="x", expand=True)

        tk.Frame(opts_row, bg=BG, width=8).pack(side="left")

        self._opt_qual = self._option_card(opts_row, "QUALITY", self.quality_var,
                                           ["Best", "1080p", "720p", "480p", "360p"])
        self._opt_qual.pack(side="left", fill="x", expand=True)

        tk.Frame(opts_row, bg=BG, width=8).pack(side="left")

        save_card = tk.Frame(opts_row, bg=CARD,
                             highlightbackground=BORDER, highlightthickness=1,
                             cursor="hand2")
        save_card.pack(side="left", fill="x", expand=True)
        tk.Label(save_card, text="SAVE TO", font=("Helvetica", 9, "bold"),
                 bg=CARD, fg=MUTED).pack(anchor="w", padx=12, pady=(10, 0))
        save_val = tk.Frame(save_card, bg=CARD)
        save_val.pack(fill="x", padx=12, pady=(2, 10))
        self.folder_label = tk.Label(save_val,
                                     text=self._short_path(self.download_path),
                                     font=("Helvetica", 12, "bold"),
                                     bg=CARD, fg=ACCENT, anchor="w")
        self.folder_label.pack(side="left")
        tk.Label(save_val, text="▾", font=FONT_XS, bg=CARD, fg=DIM).pack(side="left", padx=(4, 0))
        save_card.bind("<Button-1>", lambda e: self._pick_folder())
        for w in save_card.winfo_children():
            w.bind("<Button-1>", lambda e: self._pick_folder())

        # Update pills when format/quality change
        self.format_var.trace_add("write",  lambda *_: self._sync_pills())
        self.quality_var.trace_add("write", lambda *_: self._sync_pills())

        # ── Progress card ──────────────────────────────────────────────────
        self._build_progress_card(inner)

        # ── Download button ────────────────────────────────────────────────
        self.dl_btn = tk.Button(inner, text="Download",
                                font=("Helvetica", 15, "bold"),
                                bg=ACCENT, fg="#fff", relief="flat", bd=0,
                                activebackground="#3d6b4a",
                                activeforeground="#fff",
                                cursor="hand2", state="disabled",
                                command=self._start_download)
        self.dl_btn.pack(fill="x", pady=(0, 20), ipady=13)

        # ── Divider ────────────────────────────────────────────────────────
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x",
                                                       padx=0, pady=(0, 0))

        # ── History section ────────────────────────────────────────────────
        self._build_history_section(PAD)

        # ── TTK style ──────────────────────────────────────────────────────
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Canopy.Horizontal.TProgressbar",
                        troughcolor=PROG_TRK, background=ACCENT,
                        thickness=5, borderwidth=0, relief="flat")
        style.configure("TScrollbar", background=BG, troughcolor=BG,
                        borderwidth=0, relief="flat")

    def _option_card(self, parent, label, var, choices):
        card = tk.Frame(parent, bg=CARD,
                        highlightbackground=BORDER, highlightthickness=1,
                        cursor="hand2")
        tk.Label(card, text=label, font=("Helvetica", 9, "bold"),
                 bg=CARD, fg=MUTED).pack(anchor="w", padx=12, pady=(10, 0))
        val_row = tk.Frame(card, bg=CARD)
        val_row.pack(fill="x", padx=12, pady=(2, 10))
        val_lbl = tk.Label(val_row, textvariable=var,
                           font=("Helvetica", 14, "bold"),
                           bg=CARD, fg=FG, anchor="w")
        val_lbl.pack(side="left")
        tk.Label(val_row, text="▾", font=FONT_XS, bg=CARD, fg=DIM).pack(
            side="left", padx=(4, 0))

        def show_menu(e=None):
            m = tk.Menu(card, tearoff=0, font=FONT_SM,
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
        fmt = self.format_var.get()
        qual = self.quality_var.get()
        self.vc_fmt_pill.config(text=fmt.upper())
        self.vc_qual_pill.config(text=qual)

    def _build_progress_card(self, parent):
        self.prog_card = tk.Frame(parent, bg=CARD,
                                  highlightbackground=BORDER, highlightthickness=1)
        self.prog_card.pack(fill="x", pady=(0, 10))

        pc = tk.Frame(self.prog_card, bg=CARD)
        pc.pack(fill="x", padx=14, pady=(12, 8))

        # Status row
        status_row = tk.Frame(pc, bg=CARD)
        status_row.pack(fill="x")
        self.prog_status = tk.Label(status_row, text="Ready",
                                    font=("Helvetica", 12, "bold"),
                                    bg=CARD, fg=ACCENT, anchor="w")
        self.prog_status.pack(side="left")
        self.prog_detail = tk.Label(status_row, text="",
                                    font=FONT_XS, bg=CARD, fg=MUTED, anchor="e")
        self.prog_detail.pack(side="right")

        # Progress bar
        self.act_progress_var = tk.DoubleVar()
        self.act_bar = ttk.Progressbar(pc, variable=self.act_progress_var,
                                       maximum=100,
                                       style="Canopy.Horizontal.TProgressbar")
        self.act_bar.pack(fill="x", pady=(8, 0))

        # Log toggle
        tog_row = tk.Frame(pc, bg=CARD, cursor="hand2")
        tog_row.pack(fill="x", pady=(8, 0))
        self.log_chevron = tk.Label(tog_row, text="▾", font=("Helvetica", 10),
                                    bg=CARD, fg=DIM, cursor="hand2")
        self.log_chevron.pack(side="left")
        tk.Label(tog_row, text="  Activity log", font=FONT_XS,
                 bg=CARD, fg=MUTED, cursor="hand2").pack(side="left")
        tog_row.bind("<Button-1>",      lambda e: self._toggle_activity())
        self.log_chevron.bind("<Button-1>", lambda e: self._toggle_activity())
        for w in tog_row.winfo_children():
            w.bind("<Button-1>", lambda e: self._toggle_activity())

        # Dark terminal log
        self.log_body = tk.Frame(pc, bg=CARD)
        self.log_body.pack(fill="x", pady=(6, 0))

        log_bg_frame = tk.Frame(self.log_body, bg=LOG_BG)
        log_bg_frame.pack(fill="x")

        self._log_text = tk.Text(log_bg_frame, bg=LOG_BG, fg=LOG_MUT,
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
        hist_hdr = tk.Frame(self.root, bg=BG)
        hist_hdr.pack(fill="x", padx=PAD, pady=(16, 10))
        tk.Label(hist_hdr, text="Recent Downloads",
                 font=FONT_H, bg=BG, fg=FG).pack(side="left")
        self.hist_count = tk.Label(hist_hdr, text="", font=FONT_XS, bg=BG, fg=MUTED)
        self.hist_count.pack(side="left", padx=(8, 0))

        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=PAD, pady=(0, 24))

        self.hist_canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(container, orient="vertical",
                           command=self.hist_canvas.yview)
        self.hist_inner = tk.Frame(self.hist_canvas, bg=BG)
        self.hist_inner.bind(
            "<Configure>",
            lambda e: self.hist_canvas.configure(
                scrollregion=self.hist_canvas.bbox("all")))
        self.hist_canvas.create_window((0, 0), window=self.hist_inner, anchor="nw")
        self.hist_canvas.configure(yscrollcommand=sb.set)
        self.hist_canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.hist_canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.hist_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

    # ── Activity log helpers ───────────────────────────────────────────────

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
        """Update the progress status label (replaces the old pill badge)."""
        color_map = {
            "Idle":        (MUTED, CARD),
            "Fetching":    (ACCENT, CARD),
            "Ready":       (ACCENT, CARD),
            "Downloading": (ACCENT, CARD),
            "Done":        (ACCENT, CARD),
            "Error":       ("#cc3333", CARD),
        }
        color = color_map.get(text, (MUTED, CARD))[0]
        self.prog_status.config(text=text, fg=color)

    def _toggle_activity(self):
        self.activity_open = not self.activity_open
        if self.activity_open:
            self.log_body.pack(fill="x", pady=(6, 0))
            self.log_chevron.config(text="▾")
        else:
            self.log_body.pack_forget()
            self.log_chevron.config(text="▸")

    # ── Actions ────────────────────────────────────────────────────────────

    def _pick_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_path)
        if folder:
            self.download_path = folder
            self.folder_label.config(text=self._short_path(folder))

    def _fetch_info(self):
        url = self.url_var.get().strip()
        if not url or self.is_fetching or self.is_downloading:
            return
        self.is_fetching = True
        self.fetch_btn.config(state="disabled")
        self.dl_btn.config(state="disabled")
        self.vc_title.config(text="Fetching video info...", fg=MUTED)
        self.vc_meta.config(text="")
        self._log_clear()
        self._log(f"Fetching: {url[:60]}", "green")
        self._pill("Fetching")
        self.act_progress_var.set(0)
        self.prog_detail.config(text="")
        threading.Thread(target=self._do_fetch, args=(url,), daemon=True).start()

    def _do_fetch(self, url):
        self._write_log(f"Fetching info for: {url}")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                    "skip_download": True}) as ydl:
                self.info = ydl.extract_info(url, download=False)
            title    = self.info.get("title", "Unknown")
            uploader = self.info.get("uploader", "")
            duration = self.info.get("duration_string", "")
            thumb_url = self.info.get("thumbnail", "")
            video_id  = self.info.get("id", "")
            self._write_log(f"Info OK  title={title!r}")
            parts   = [p for p in (uploader, duration) if p]
            meta    = "  ·  ".join(parts)
            self.root.after(0, lambda: self._on_fetch_done(title, meta, thumb_url, video_id, True))
        except Exception as e:
            self._write_log(f"Fetch error: {e}")
            self.root.after(0, lambda: self._on_fetch_done(str(e), "", "", "", False))

    def _on_fetch_done(self, title, meta, thumb_url, video_id, success):
        self.is_fetching = False
        self.fetch_btn.config(state="normal")
        if success:
            self.vc_title.config(text=title, fg=FG)
            self.vc_meta.config(text=meta)
            self.dl_btn.config(state="normal")
            self._log(f"Found: {title[:55]}", "muted")
            if meta:
                self._log(meta, "dim")
            self._pill("Ready")
            if thumb_url and video_id:
                threading.Thread(target=self._load_vc_thumb,
                                 args=(thumb_url, video_id), daemon=True).start()
        else:
            self.vc_title.config(text="Could not fetch video info", fg="#cc3333")
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
                img   = Image.open(cached).convert("RGB")
                img   = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                def _apply():
                    self._vc_photo = photo
                    self.vc_thumb_lbl.config(image=photo, text="", bg="#1c1c1e")
                    self.vc_thumb_box.config(bg="#1c1c1e")
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

    # ── Download picker dialog ─────────────────────────────────────────────

    def _show_download_picker(self):
        title     = self.info.get("title", "Unknown")
        uploader  = self.info.get("uploader", "")
        duration  = self.info.get("duration_string", "")
        video_id  = self.info.get("id", "")

        DIALOG_W = 400
        THUMB_DH = 225

        dlg = tk.Toplevel(self.root)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.configure(bg=CARD)
        dlg.transient(self.root)
        dlg.grab_set()

        # Thumbnail
        thumb_bg = tk.Frame(dlg, bg="#c8e6d4", width=DIALOG_W, height=THUMB_DH)
        thumb_bg.pack(fill="x")
        thumb_bg.pack_propagate(False)
        thumb_lbl = tk.Label(thumb_bg, bg="#c8e6d4", text="▶",
                             font=("Helvetica", 40), fg=ACCENT)
        thumb_lbl.pack(expand=True)
        dlg._photo = None

        def _load():
            cached = os.path.join(THUMB_CACHE, f"{video_id}.jpg") if video_id else ""
            if cached and os.path.exists(cached) and PILLOW:
                try:
                    img   = Image.open(cached).convert("RGB")
                    img   = img.resize((DIALOG_W, THUMB_DH), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    def _apply():
                        if dlg.winfo_exists():
                            thumb_lbl.config(image=photo, text="", bg="#1c1c1e")
                            thumb_bg.config(bg="#1c1c1e")
                            dlg._photo = photo
                    dlg.after(0, _apply)
                except Exception:
                    pass

        threading.Thread(target=_load, daemon=True).start()

        # Info
        info_f = tk.Frame(dlg, bg=CARD)
        info_f.pack(fill="x", padx=20, pady=(16, 12))
        tk.Label(info_f, text=title, font=("Helvetica", 13, "bold"),
                 bg=CARD, fg=FG, anchor="w",
                 wraplength=360, justify="left").pack(fill="x")
        detail = "  ·  ".join(p for p in (uploader, duration) if p)
        if detail:
            tk.Label(info_f, text=detail, font=FONT_XS,
                     bg=CARD, fg=MUTED, anchor="w").pack(fill="x", pady=(5, 0))

        tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x")

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

            row = tk.Frame(dlg, bg=CARD, cursor="hand2")
            row.pack(fill="x")
            pad = tk.Frame(row, bg=CARD)
            pad.pack(fill="x", padx=20, pady=13)
            tk.Label(pad, text=icon, font=("Helvetica", 16),
                     bg=CARD, fg=ACCENT, width=2).pack(side="left")
            col = tk.Frame(pad, bg=CARD)
            col.pack(side="left", padx=(12, 0), fill="x", expand=True)
            tk.Label(col, text=opt_label, font=("Helvetica", 13, "bold"),
                     bg=CARD, fg=FG, anchor="w").pack(anchor="w")
            tk.Label(col, text=sub, font=FONT_XS,
                     bg=CARD, fg=MUTED, anchor="w").pack(anchor="w", pady=(2, 0))
            tk.Label(pad, text="›", font=("Helvetica", 20),
                     bg=CARD, fg=DIM).pack(side="right")
            tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x")
            self._bind_picker_row(row, _pick)

        tk.Button(dlg, text="Cancel", font=FONT_SM,
                  bg=CARD, fg=MUTED, relief="flat", bd=0,
                  cursor="hand2", pady=13,
                  activebackground=CARD, activeforeground=FG,
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
            widget.config(bg=color)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._row_bg(child, color)

    def _begin_download(self, fmt, quality):
        if not self.info or self.is_downloading:
            return
        url      = self.url_var.get().strip()
        title    = self.info.get("title", "Unknown")
        video_id = self.info.get("id", "unknown")
        self.is_downloading      = True
        self._download_completed = False
        self._open_dl_log(video_id, title)
        self.dl_btn.config(state="disabled")
        self.fetch_btn.config(state="disabled")
        self.act_progress_var.set(0)
        self.prog_detail.config(text="")
        self._log(f"Starting {fmt.upper()} {quality} download...", "green")
        self._pill("Downloading")
        threading.Thread(target=self._do_download,
                         args=(url, fmt, quality), daemon=True).start()

    # ── Download logic (unchanged) ─────────────────────────────────────────

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
                    ydl_fmt = f"bestvideo[ext={fmt}]+bestaudio/bestvideo+bestaudio/best"
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
            fp = info.get("filepath") or info.get("filename", "")
            if fp and os.path.isfile(fp):
                self._last_filename = fp
                self._write_log(f"Post-process output: {fp}")

    def _set_progress(self, pct, detail):
        self.act_progress_var.set(pct)
        self.prog_detail.config(text=detail)
        self._log_update(f"Downloading  {detail}", "active")

    def _on_download_done(self):
        if self._download_completed:
            return
        self._download_completed = True
        self.is_downloading = False
        self.act_progress_var.set(100)
        self.prog_detail.config(text="")
        self._write_log(f"Download complete. Folder: {self.download_path}")
        self._close_dl_log()
        self._log_update("Download complete!", "success")
        self._log(f"Saved to {self._short_path(self.download_path)}", "dim")
        self._pill("Done")
        self.dl_btn.config(state="normal")
        self.fetch_btn.config(state="normal")
        self._refresh_history()

    def _on_download_error(self, error):
        self.is_downloading = False
        self._write_log(f"Download failed: {error}")
        self._close_dl_log()
        self._log_update(f"Failed: {error[:80]}", "error")
        self._pill("Error")
        self.dl_btn.config(state="normal")
        self.fetch_btn.config(state="normal")
        messagebox.showerror("Download Error", error[:300])

    # ── Thumbnails ─────────────────────────────────────────────────────────

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
            img   = Image.open(path).convert("RGB")
            img   = img.resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._thumb_refs[video_id] = photo
            return photo
        except Exception:
            return None

    # ── History rendering ──────────────────────────────────────────────────

    def _refresh_history(self):
        for w in self.hist_inner.winfo_children():
            w.destroy()

        n = len(self.history)
        self.hist_count.config(
            text=f"{n} item{'s' if n != 1 else ''}" if n else "")

        if not self.history:
            tk.Label(self.hist_inner, text="No downloads yet",
                     font=FONT_SM, bg=BG, fg=MUTED).pack(pady=24)
            return

        for entry in self.history:
            self._render_row(entry)

    def _render_row(self, entry):
        card = tk.Frame(self.hist_inner, bg=CARD,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 8))

        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=14, pady=12)

        # Thumbnail
        file_path   = entry.get("file_path", "")
        file_exists = bool(file_path and os.path.isfile(file_path))

        thumb_box = tk.Frame(inner, bg="#c8e6d4",
                             width=HIST_TW, height=HIST_TH)
        thumb_box.pack(side="left")
        thumb_box.pack_propagate(False)

        photo = self._load_thumb(entry.get("video_id", ""))
        if photo:
            tk.Label(thumb_box, image=photo, bg="#1c1c1e").pack(fill="both", expand=True)
            thumb_box.config(bg="#1c1c1e")
        else:
            tk.Label(thumb_box, text="▶", font=("Helvetica", 14),
                     bg="#c8e6d4", fg=ACCENT).pack(expand=True)

        # Text
        text_f = tk.Frame(inner, bg=CARD)
        text_f.pack(side="left", fill="x", expand=True, padx=(12, 0))

        title = entry.get("title", "Unknown")
        tk.Label(text_f, text=title[:56], font=("Helvetica", 12, "bold"),
                 bg=CARD, fg=FG, anchor="w").pack(fill="x")

        meta_parts = []
        dt = entry.get("downloaded_at", "")
        if dt:
            meta_parts.append(dt[:10])
        save_path = entry.get("save_path", "")
        if save_path:
            meta_parts.append(self._short_path(save_path))
        if file_path and not file_exists:
            meta_parts.append("⚠ file removed")

        meta_lbl = tk.Label(text_f, text="  ·  ".join(meta_parts),
                            font=FONT_XS, bg=CARD, anchor="w",
                            fg="#cc3333" if (file_path and not file_exists) else MUTED)
        meta_lbl.pack(fill="x", pady=(3, 0))

        # Right side actions
        right = tk.Frame(inner, bg=CARD)
        right.pack(side="right", padx=(8, 0))

        fmt = entry.get("format", "").upper()
        if fmt:
            tk.Label(right, text=fmt, font=FONT_PILL,
                     bg=PILL_BG, fg=PILL_FG,
                     padx=8, pady=2).pack(anchor="e")

        if save_path and os.path.isdir(save_path):
            tk.Button(right, text="⌁ Finder", font=("Helvetica", 10, "bold"),
                      bg=CARD, fg=ACCENT, relief="flat", bd=0,
                      cursor="hand2",
                      activebackground=CARD, activeforeground="#3d6b4a",
                      command=lambda p=save_path: os.system(f'open "{p}"')
                      ).pack(anchor="e", pady=(6, 0))

        menu_btn = tk.Button(right, text="···",
                             font=("Helvetica", 14, "bold"),
                             bg=CARD, fg=MUTED, relief="flat", bd=0,
                             cursor="hand2",
                             activebackground=CARD, activeforeground=FG)
        menu_btn.pack(anchor="e", pady=(4, 0))
        menu_btn.config(
            command=lambda e=entry, b=menu_btn: self._show_row_menu(b, e))

    # ── Row context menu ───────────────────────────────────────────────────

    def _show_row_menu(self, btn, entry):
        menu = tk.Menu(self.root, tearoff=0, font=FONT_SM,
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

    # ── Utilities ──────────────────────────────────────────────────────────

    def _short_path(self, path):
        home = os.path.expanduser("~")
        return ("~" + path[len(home):]) if path.startswith(home) else path


def main():
    root = tk.Tk()
    CanopyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
