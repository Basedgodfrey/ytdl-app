import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import yt_dlp
import os
import sys


class YTDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YT Downloader")
        self.root.geometry("560x420")
        self.root.resizable(False, False)
        self.root.configure(bg="#0f0f0f")

        self.download_path = os.path.expanduser("~/Downloads")
        self.formats = []
        self.info = None
        self.is_fetching = False

        self._build_ui()

    def _build_ui(self):
        PAD = 18
        BG = "#0f0f0f"
        CARD = "#1a1a1a"
        ACCENT = "#ff0000"
        FG = "#ffffff"
        MUTED = "#888888"
        FONT = ("Helvetica Neue", 13)
        FONT_SM = ("Helvetica Neue", 11)

        # Title
        tk.Label(self.root, text="YT Downloader", font=("Helvetica Neue", 20, "bold"),
                 bg=BG, fg=FG).pack(pady=(PAD, 4))
        tk.Label(self.root, text="Paste a YouTube or Shorts URL to get started",
                 font=FONT_SM, bg=BG, fg=MUTED).pack(pady=(0, PAD))

        # URL row
        url_frame = tk.Frame(self.root, bg=BG)
        url_frame.pack(fill="x", padx=PAD)

        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(url_frame, textvariable=self.url_var,
                                  font=FONT, bg=CARD, fg=FG,
                                  insertbackground=FG, relief="flat",
                                  bd=0, highlightthickness=1,
                                  highlightbackground="#333", highlightcolor=ACCENT)
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=8, ipadx=8)
        self.url_entry.bind("<Return>", lambda e: self._fetch_info())

        self.fetch_btn = tk.Button(url_frame, text="Fetch", font=FONT,
                                   bg=ACCENT, fg=FG, relief="flat",
                                   activebackground="#cc0000", activeforeground=FG,
                                   cursor="hand2", bd=0,
                                   command=self._fetch_info)
        self.fetch_btn.pack(side="left", padx=(8, 0), ipady=8, ipadx=14)

        # Video info card
        self.info_frame = tk.Frame(self.root, bg=CARD, pady=10, padx=14)
        self.info_frame.pack(fill="x", padx=PAD, pady=(14, 0))
        self.title_label = tk.Label(self.info_frame, text="No video loaded",
                                    font=FONT_SM, bg=CARD, fg=MUTED,
                                    wraplength=480, justify="left", anchor="w")
        self.title_label.pack(fill="x")

        # Format + quality row
        options_frame = tk.Frame(self.root, bg=BG)
        options_frame.pack(fill="x", padx=PAD, pady=(14, 0))

        tk.Label(options_frame, text="Format", font=FONT_SM, bg=BG, fg=MUTED).grid(row=0, column=0, sticky="w")
        tk.Label(options_frame, text="Quality", font=FONT_SM, bg=BG, fg=MUTED).grid(row=0, column=1, sticky="w", padx=(16, 0))

        self.format_var = tk.StringVar(value="mp4")
        format_menu = ttk.Combobox(options_frame, textvariable=self.format_var,
                                   values=["mp4", "mp3", "webm", "m4a"],
                                   state="readonly", width=10, font=FONT_SM)
        format_menu.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.quality_var = tk.StringVar(value="Best")
        self.quality_menu = ttk.Combobox(options_frame, textvariable=self.quality_var,
                                         values=["Best", "1080p", "720p", "480p", "360p"],
                                         state="readonly", width=12, font=FONT_SM)
        self.quality_menu.grid(row=1, column=1, sticky="w", padx=(16, 0), pady=(4, 0))

        # Save folder
        folder_frame = tk.Frame(self.root, bg=BG)
        folder_frame.pack(fill="x", padx=PAD, pady=(14, 0))
        tk.Label(folder_frame, text="Save to", font=FONT_SM, bg=BG, fg=MUTED).pack(side="left")
        self.folder_label = tk.Label(folder_frame, text=self.download_path,
                                     font=FONT_SM, bg=BG, fg="#aaaaaa",
                                     cursor="hand2")
        self.folder_label.pack(side="left", padx=(8, 0))
        self.folder_label.bind("<Button-1>", lambda e: self._pick_folder())

        # Progress bar + status
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(self.root, variable=self.progress_var,
                                        maximum=100, length=524)
        self.progress.pack(padx=PAD, pady=(14, 0))

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var,
                 font=FONT_SM, bg=BG, fg=MUTED).pack(pady=(6, 0))

        # Download button
        self.dl_btn = tk.Button(self.root, text="Download",
                                font=("Helvetica Neue", 14, "bold"),
                                bg=ACCENT, fg=FG, relief="flat",
                                activebackground="#cc0000", activeforeground=FG,
                                cursor="hand2", bd=0, state="disabled",
                                command=self._start_download)
        self.dl_btn.pack(pady=(14, 0), ipadx=24, ipady=10)

        # Style comboboxes
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TCombobox", fieldbackground="#1a1a1a",
                        background="#1a1a1a", foreground="#ffffff",
                        selectbackground="#1a1a1a", selectforeground="#ffffff",
                        arrowcolor="#ffffff")

    def _pick_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_path)
        if folder:
            self.download_path = folder
            self.folder_label.config(text=folder)

    def _fetch_info(self):
        url = self.url_var.get().strip()
        if not url:
            return
        if self.is_fetching:
            return
        self.is_fetching = True
        self.fetch_btn.config(state="disabled")
        self.dl_btn.config(state="disabled")
        self.status_var.set("Fetching video info...")
        self.progress_var.set(0)
        threading.Thread(target=self._do_fetch, args=(url,), daemon=True).start()

    def _do_fetch(self, url):
        try:
            ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.info = ydl.extract_info(url, download=False)
            title = self.info.get("title", "Unknown title")
            duration = self.info.get("duration_string", "")
            uploader = self.info.get("uploader", "")
            display = f"{title}"
            if uploader:
                display += f"  |  {uploader}"
            if duration:
                display += f"  |  {duration}"
            self.root.after(0, lambda: self._on_fetch_done(display, success=True))
        except Exception as e:
            self.root.after(0, lambda: self._on_fetch_done(str(e), success=False))

    def _on_fetch_done(self, message, success):
        self.is_fetching = False
        self.fetch_btn.config(state="normal")
        if success:
            self.title_label.config(text=message, fg="#dddddd")
            self.dl_btn.config(state="normal")
            self.status_var.set("Ready to download")
        else:
            self.title_label.config(text="Could not fetch video info", fg="#ff4444")
            self.status_var.set(f"Error: {message[:80]}")

    def _start_download(self):
        if not self.info:
            return
        url = self.url_var.get().strip()
        fmt = self.format_var.get()
        quality = self.quality_var.get()
        self.dl_btn.config(state="disabled")
        self.fetch_btn.config(state="disabled")
        self.progress_var.set(0)
        self.status_var.set("Starting download...")
        threading.Thread(target=self._do_download,
                         args=(url, fmt, quality), daemon=True).start()

    def _do_download(self, url, fmt, quality):
        try:
            # Build format string
            if fmt == "mp3":
                ydl_fmt = "bestaudio/best"
                postprocessors = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            elif fmt == "m4a":
                ydl_fmt = "bestaudio[ext=m4a]/bestaudio/best"
                postprocessors = []
            else:
                height_map = {"1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
                if quality in height_map:
                    h = height_map[quality]
                    ydl_fmt = f"bestvideo[height<={h}][ext={fmt}]+bestaudio/bestvideo[height<={h}]+bestaudio/best"
                else:
                    ydl_fmt = f"bestvideo[ext={fmt}]+bestaudio/bestvideo+bestaudio/best"
                postprocessors = []

            ydl_opts = {
                "format": ydl_fmt,
                "outtmpl": os.path.join(self.download_path, "%(title)s.%(ext)s"),
                "merge_output_format": fmt if fmt not in ("mp3", "m4a") else None,
                "progress_hooks": [self._progress_hook],
                "quiet": True,
                "no_warnings": True,
            }
            if postprocessors:
                ydl_opts["postprocessors"] = postprocessors

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            self.root.after(0, self._on_download_done)
        except Exception as e:
            self.root.after(0, lambda: self._on_download_error(str(e)))

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("_speed_str", "")
            eta = d.get("_eta_str", "")
            if total > 0:
                pct = downloaded / total * 100
                self.root.after(0, lambda p=pct: self.progress_var.set(p))
            status = "Downloading..."
            if speed:
                status += f"  {speed}"
            if eta:
                status += f"  ETA {eta}"
            self.root.after(0, lambda s=status: self.status_var.set(s))
        elif d["status"] == "finished":
            self.root.after(0, lambda: self.status_var.set("Processing..."))
            self.root.after(0, lambda: self.progress_var.set(95))

    def _on_download_done(self):
        self.progress_var.set(100)
        self.status_var.set("Done! Saved to " + self.download_path)
        self.dl_btn.config(state="normal")
        self.fetch_btn.config(state="normal")
        messagebox.showinfo("Download Complete",
                            f"File saved to:\n{self.download_path}")

    def _on_download_error(self, error):
        self.status_var.set("Download failed")
        self.dl_btn.config(state="normal")
        self.fetch_btn.config(state="normal")
        messagebox.showerror("Download Error", error[:200])


def main():
    root = tk.Tk()
    app = YTDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
