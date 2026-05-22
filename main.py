import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import yt_dlp
import os
import sys
import json
import urllib.request
import datetime

try:
    from PIL import Image, ImageTk
    PILLOW = True
except ImportError:
    PILLOW = False

HISTORY_FILE = os.path.expanduser("~/.ytdl_history.json")
THUMB_CACHE  = os.path.expanduser("~/.ytdl_cache/thumbnails")
LOG_FILE     = os.path.expanduser("~/.ytdl_debug.log")


def _find_ffmpeg():
    """Return ffmpeg path: bundled app → Homebrew → PATH → None."""
    # PyInstaller bundle unpacks binaries to sys._MEIPASS
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
    """Routes yt-dlp log messages to the session log file."""
    def __init__(self, write_fn):
        self._write = write_fn

    def debug(self, msg):
        if msg.startswith("[debug]"):
            return          # skip verbose debug noise
        self._write(f"[yt-dlp] {msg}")

    def info(self, msg):
        self._write(f"[yt-dlp] {msg}")

    def warning(self, msg):
        self._write(f"[yt-dlp WARN] {msg}")

    def error(self, msg):
        self._write(f"[yt-dlp ERROR] {msg}")

# ── Apple-inspired palette ─────────────────────────────────────────────────
BG      = "#f5f4f7"
CARD    = "#ffffff"
SEP     = "#e5e5ea"
ACCENT  = "#007aff"
DL_RED  = "#ff3b30"
FG      = "#1d1d1f"
MUTED   = "#6c6c70"
GREEN   = "#34c759"
YELLOW  = "#ff9500"

FONT_H   = ("Helvetica", 24, "bold")      # title
FONT_SUB = ("Helvetica", 12)              # subtitle / labels
FONT     = ("Helvetica", 13)              # body
FONT_MED = ("Helvetica", 13, "bold")      # medium emphasis
FONT_SM  = ("Helvetica", 11)              # small
FONT_XS  = ("Helvetica", 10)             # caption
FONT_MONO = ("Menlo", 10)                # icons / log

THUMB_W, THUMB_H = 96, 54


class YTDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YT Downloader")
        self.root.geometry("700x780")
        self.root.minsize(640, 600)
        self.root.configure(bg=BG)

        self.download_path  = os.path.expanduser("~/Downloads")
        self.info           = None
        self.is_fetching    = False
        self.is_downloading = False
        self.activity_open  = True
        self._thumb_refs    = {}

        self.history = self._load_history()
        os.makedirs(THUMB_CACHE, exist_ok=True)
        self._setup_log()
        self._build_ui()
        self._refresh_history()

    # ── Session log ────────────────────────────────────────────────────────

    def _setup_log(self):
        self._log_file = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
        self._write_log("=" * 60)
        self._write_log(f"Session started  ffmpeg={FFMPEG_PATH or 'NOT FOUND'}")
        self._write_log(f"Python={sys.executable}")

    def _write_log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            self._log_file.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

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
        PAD = 20

        # ── Title ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=PAD, pady=(28, 0))
        tk.Label(hdr, text="YT Downloader", font=FONT_H, bg=BG, fg=FG).pack(side="left")

        # ── URL card ───────────────────────────────────────────────────────
        url_card = tk.Frame(self.root, bg=CARD,
                            highlightbackground=SEP, highlightthickness=1)
        url_card.pack(fill="x", padx=PAD, pady=(14, 0))

        url_inner = tk.Frame(url_card, bg=CARD)
        url_inner.pack(fill="x", padx=16, pady=14)

        tk.Label(url_inner, text="URL", font=FONT_XS,
                 bg=CARD, fg=MUTED).pack(anchor="w")

        url_row = tk.Frame(url_inner, bg=CARD)
        url_row.pack(fill="x", pady=(5, 0))

        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(url_row, textvariable=self.url_var,
                                  font=FONT, bg=BG, fg=FG,
                                  insertbackground=FG, relief="flat", bd=0,
                                  highlightthickness=1,
                                  highlightbackground=SEP,
                                  highlightcolor=ACCENT)
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=8, ipadx=8)
        self.url_entry.bind("<Return>", lambda e: self._fetch_info())

        self.fetch_btn = tk.Button(url_row, text="Fetch", font=("Helvetica", 12, "bold"),
                                   bg=ACCENT, fg="#fff", relief="flat", bd=0,
                                   activebackground="#0051d5",
                                   activeforeground="#fff",
                                   cursor="hand2",
                                   command=self._fetch_info)
        self.fetch_btn.pack(side="left", padx=(8, 0), ipady=8, ipadx=16)

        # video info strip
        tk.Frame(url_card, bg=SEP, height=1).pack(fill="x")
        info_inner = tk.Frame(url_card, bg=CARD)
        info_inner.pack(fill="x", padx=16, pady=10)
        self.title_label = tk.Label(info_inner, text="Paste a YouTube URL above",
                                    font=("Helvetica", 12), bg=CARD, fg=MUTED,
                                    anchor="w", wraplength=630, justify="left")
        self.title_label.pack(fill="x")

        # ── Options row ────────────────────────────────────────────────────
        opts = tk.Frame(self.root, bg=BG)
        opts.pack(fill="x", padx=PAD, pady=(14, 0))

        def _labeled_combo(parent, label, var, values, width):
            f = tk.Frame(parent, bg=BG)
            f.pack(side="left")
            tk.Label(f, text=label, font=FONT_XS, bg=BG, fg=MUTED).pack(anchor="w")
            cb = ttk.Combobox(f, textvariable=var, values=values,
                              state="readonly", width=width, font=FONT_SM)
            cb.pack(pady=(4, 0))
            return f

        self.format_var  = tk.StringVar(value="mp4")
        self.quality_var = tk.StringVar(value="Best")
        _labeled_combo(opts, "Format",  self.format_var,
                       ["mp4", "mp3", "webm", "m4a"], 9)
        tk.Frame(opts, bg=BG, width=12).pack(side="left")
        _labeled_combo(opts, "Quality", self.quality_var,
                       ["Best", "1080p", "720p", "480p", "360p"], 11)

        folder_f = tk.Frame(opts, bg=BG)
        folder_f.pack(side="left", padx=(12, 0))
        tk.Label(folder_f, text="Save to", font=FONT_XS, bg=BG, fg=MUTED).pack(anchor="w")
        self.folder_label = tk.Label(folder_f,
                                     text=self._short_path(self.download_path),
                                     font=FONT_SM, bg=BG, fg=ACCENT, cursor="hand2")
        self.folder_label.pack(pady=(4, 0), anchor="w")
        self.folder_label.bind("<Button-1>", lambda e: self._pick_folder())

        self.dl_btn = tk.Button(opts, text="Download",
                                font=("Helvetica", 14, "bold"),
                                bg=DL_RED, fg="#fff", relief="flat", bd=0,
                                activebackground="#c0392b",
                                activeforeground="#fff",
                                cursor="hand2", state="disabled",
                                command=self._start_download)
        self.dl_btn.pack(side="right", ipady=9, ipadx=22)

        # ── Activity panel ─────────────────────────────────────────────────
        self._build_activity_panel(PAD)

        # ── History section ────────────────────────────────────────────────
        self._build_history_section(PAD)

        # ── TTK styling ────────────────────────────────────────────────────
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TCombobox",
                        fieldbackground=CARD, background=CARD,
                        foreground=FG, selectbackground=CARD,
                        selectforeground=FG, arrowcolor=MUTED)
        style.configure("Act.Horizontal.TProgressbar",
                        troughcolor=SEP, background=ACCENT, thickness=4)

    def _build_activity_panel(self, PAD):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="x", padx=PAD, pady=(14, 0))

        # Header (always visible)
        hdr_card = tk.Frame(outer, bg=CARD,
                            highlightbackground=SEP, highlightthickness=1)
        hdr_card.pack(fill="x")
        hdr_inner = tk.Frame(hdr_card, bg=CARD)
        hdr_inner.pack(fill="x", padx=16, pady=10)

        self.act_toggle = tk.Label(hdr_inner, text="▾  Activity",
                                   font=("Helvetica", 12, "bold"),
                                   bg=CARD, fg=FG, cursor="hand2")
        self.act_toggle.pack(side="left")
        self.act_toggle.bind("<Button-1>", lambda e: self._toggle_activity())

        self.act_pill = tk.Label(hdr_inner, text="Idle",
                                 font=FONT_XS, bg=SEP, fg=MUTED,
                                 padx=8, pady=2)
        self.act_pill.pack(side="left", padx=(10, 0))

        # Body (collapsible)
        self.act_body = tk.Frame(outer, bg=CARD,
                                 highlightbackground=SEP, highlightthickness=1)
        self.act_body.pack(fill="x")

        tk.Frame(self.act_body, bg=SEP, height=1).pack(fill="x")

        self.act_log = tk.Frame(self.act_body, bg=CARD)
        self.act_log.pack(fill="x", padx=16, pady=(10, 6))

        self.act_progress_var = tk.DoubleVar()
        self.act_bar = ttk.Progressbar(self.act_body,
                                       variable=self.act_progress_var,
                                       maximum=100,
                                       style="Act.Horizontal.TProgressbar")
        # bar hidden until download starts

        self._log("Waiting for a URL...", "muted")

    def _build_history_section(self, PAD):
        hist_hdr = tk.Frame(self.root, bg=BG)
        hist_hdr.pack(fill="x", padx=PAD, pady=(20, 6))
        tk.Label(hist_hdr, text="Recent Downloads",
                 font=("Helvetica", 14, "bold"),
                 bg=BG, fg=FG).pack(side="left")
        self.hist_count = tk.Label(hist_hdr, text="", font=FONT_XS, bg=BG, fg=MUTED)
        self.hist_count.pack(side="left", padx=(8, 0))

        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=PAD, pady=(0, 20))

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

        # mouse-wheel scroll
        self.hist_canvas.bind_all("<MouseWheel>",
            lambda e: self.hist_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

    # ── Activity helpers ───────────────────────────────────────────────────

    _ICON = {
        "muted":   ("·",  MUTED),
        "active":  ("⟳",  ACCENT),
        "success": ("✓",  GREEN),
        "error":   ("✗",  DL_RED),
        "warn":    ("!",  YELLOW),
    }

    def _log(self, text, kind="muted"):
        icon, color = self._ICON.get(kind, ("·", MUTED))
        row = tk.Frame(self.act_log, bg=CARD)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=icon, font=FONT_MONO, bg=CARD, fg=color, width=2,
                 anchor="w").pack(side="left")
        tk.Label(row, text=text, font=FONT_XS, bg=CARD, fg=color,
                 anchor="w").pack(side="left", fill="x", expand=True)

    def _log_update(self, text, kind="active"):
        rows = self.act_log.winfo_children()
        if not rows:
            self._log(text, kind)
            return
        icon, color = self._ICON.get(kind, ("·", MUTED))
        widgets = rows[-1].winfo_children()
        if len(widgets) >= 2:
            widgets[0].config(text=icon, fg=color)
            widgets[1].config(text=text, fg=color)

    def _log_clear(self):
        for w in self.act_log.winfo_children():
            w.destroy()

    def _pill(self, text, bg=SEP, fg=MUTED):
        self.act_pill.config(text=text, bg=bg, fg=fg)

    def _toggle_activity(self):
        self.activity_open = not self.activity_open
        if self.activity_open:
            self.act_body.pack(fill="x")
            self.act_toggle.config(text="▾  Activity")
        else:
            self.act_body.pack_forget()
            self.act_toggle.config(text="▸  Activity")

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
        self.title_label.config(text="Fetching video info...", fg=MUTED)
        self._log_clear()
        self._log("Connecting to YouTube...", "active")
        self._pill("Fetching", bg="#e5f0ff", fg=ACCENT)
        self.act_progress_var.set(0)
        self.act_bar.pack_forget()
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
            self._write_log(f"Info OK  title={title!r}  uploader={uploader!r}  duration={duration!r}")
            parts   = [p for p in (title, uploader, duration) if p]
            display = "  ·  ".join(parts)
            self.root.after(0, lambda: self._on_fetch_done(display, title, True))
        except Exception as e:
            self._write_log(f"Fetch error: {e}")
            self.root.after(0, lambda: self._on_fetch_done(str(e), "", False))

    def _on_fetch_done(self, display, title, success):
        self.is_fetching = False
        self.fetch_btn.config(state="normal")
        if success:
            self.title_label.config(text=display, fg=FG)
            self.dl_btn.config(state="normal")
            self._log_update(f"Ready — {title[:55]}", "success")
            self._pill("Ready", bg="#e6f9ee", fg=GREEN)
        else:
            self.title_label.config(text="Could not fetch video info", fg=DL_RED)
            self._log_update(f"Error: {display[:80]}", "error")
            self._pill("Error", bg="#fdecea", fg=DL_RED)

    def _start_download(self):
        if not self.info or self.is_downloading:
            return
        url     = self.url_var.get().strip()
        fmt     = self.format_var.get()
        quality = self.quality_var.get()
        self.is_downloading = True
        self.dl_btn.config(state="disabled")
        self.fetch_btn.config(state="disabled")
        self.act_progress_var.set(0)
        self.act_bar.pack(fill="x", padx=16, pady=(0, 10))
        self._log(f"Starting {fmt.upper()} download...", "active")
        self._pill("Downloading", bg="#e5f0ff", fg=ACCENT)
        threading.Thread(target=self._do_download,
                         args=(url, fmt, quality), daemon=True).start()

    def _do_download(self, url, fmt, quality):
        self._write_log(f"Download start  url={url}  fmt={fmt}  quality={quality}")
        self._write_log(f"Save path: {self.download_path}")
        self._write_log(f"ffmpeg: {FFMPEG_PATH or 'NOT FOUND — merging will fail'}")
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
                if quality in h_map:
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

            if self._last_filename:
                exists = os.path.isfile(self._last_filename)
                self._write_log(f"File written: {self._last_filename}  exists={exists}")
                if not exists:
                    self._write_log("WARNING: file not found at expected path!")
            else:
                self._write_log("WARNING: no filename captured from progress hook")

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
            label = "Downloading  " + "  ·  ".join(parts)
            self.root.after(0, lambda p=pct, s=label: self._set_progress(p, s))
        elif d["status"] == "finished":
            fname = d.get("filename", "")
            if fname:
                self._last_filename = fname
                self._write_log(f"Fragment finished: {fname}")
            self.root.after(0, lambda: self._set_progress(95, "Processing..."))

    def _set_progress(self, pct, label):
        self.act_progress_var.set(pct)
        self._log_update(label, "active")

    def _on_download_done(self):
        self.is_downloading = False
        self.act_progress_var.set(100)
        self._write_log(f"Download complete. Folder: {self.download_path}")
        self._log_update("Download complete!", "success")
        self._log(f"Saved to {self._short_path(self.download_path)}", "muted")
        self._pill("Done", bg="#e6f9ee", fg=GREEN)
        self.dl_btn.config(state="normal")
        self.fetch_btn.config(state="normal")
        self._refresh_history()

    def _on_download_error(self, error):
        self.is_downloading = False
        self._log_update(f"Failed: {error[:80]}", "error")
        self._pill("Error", bg="#fdecea", fg=DL_RED)
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

    def _load_thumb(self, video_id):
        if not PILLOW:
            return None
        path = os.path.join(THUMB_CACHE, f"{video_id}.jpg")
        if not os.path.exists(path):
            return None
        try:
            img   = Image.open(path).convert("RGB")
            img   = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
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
                        highlightbackground=SEP, highlightthickness=1)
        card.pack(fill="x", pady=(0, 1))

        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=14, pady=12)

        # Thumbnail box
        thumb_box = tk.Frame(inner, bg="#e5e5ea",
                             width=THUMB_W, height=THUMB_H)
        thumb_box.pack(side="left")
        thumb_box.pack_propagate(False)

        photo = self._load_thumb(entry.get("video_id", ""))
        if photo:
            tk.Label(thumb_box, image=photo, bg="#e5e5ea").pack(
                fill="both", expand=True)
        else:
            tk.Label(thumb_box, text="▶", font=("Helvetica", 20),
                     bg="#e5e5ea", fg="#c7c7cc").pack(expand=True)

        # Text block
        text_f = tk.Frame(inner, bg=CARD)
        text_f.pack(side="left", fill="x", expand=True, padx=(12, 0))

        title = entry.get("title", "Unknown")
        tk.Label(text_f, text=title[:64], font=("Helvetica", 13, "bold"),
                 bg=CARD, fg=FG, anchor="w").pack(fill="x")

        detail_parts = []
        if entry.get("duration"):
            detail_parts.append(entry["duration"])
        if entry.get("format"):
            detail_parts.append(entry["format"].upper())
        q = entry.get("quality", "")
        if q and q != "Best":
            detail_parts.append(q)
        if entry.get("uploader"):
            detail_parts.append(entry["uploader"])
        if entry.get("downloaded_at"):
            detail_parts.append(entry["downloaded_at"][:10])

        tk.Label(text_f, text="  ·  ".join(detail_parts),
                 font=FONT_XS, bg=CARD, fg=MUTED, anchor="w").pack(
                     fill="x", pady=(3, 0))

        # Show in Finder
        save_path = entry.get("save_path", "")
        if save_path and os.path.isdir(save_path):
            tk.Button(inner, text="Show in Finder", font=FONT_XS,
                      bg=BG, fg=ACCENT, relief="flat", bd=0, cursor="hand2",
                      activebackground=BG, activeforeground="#0051d5",
                      command=lambda p=save_path: os.system(f'open "{p}"')
                      ).pack(side="right", padx=(8, 0))

    # ── Utilities ──────────────────────────────────────────────────────────

    def _short_path(self, path):
        home = os.path.expanduser("~")
        return ("~" + path[len(home):]) if path.startswith(home) else path


def main():
    root = tk.Tk()
    YTDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
