"""
canopy.core.downloader — All yt-dlp fetch/download logic.

No tkinter or UI imports.  All UI updates are dispatched via the
`ui_dispatch` callable supplied at construction time so that they always
run on the main thread (required by Python 3.14 / CustomTkinter).
"""

import os
import sys
import shutil
import threading
import yt_dlp


# ── ffmpeg discovery ──────────────────────────────────────────────────────────

def _find_ffmpeg() -> str | None:
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "ffmpeg")
        if os.path.isfile(bundled):
            return bundled
    homebrew = "/opt/homebrew/bin/ffmpeg"
    if os.path.isfile(homebrew):
        return homebrew
    return shutil.which("ffmpeg")


FFMPEG_PATH = _find_ffmpeg()


# ── Progress-display helpers (Chrome-style) ───────────────────────────────────

def _fmt_bytes(n: float) -> str:
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.2f} GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _fmt_speed(bps: float) -> str:
    if bps >= 1_073_741_824:
        return f"{bps / 1_073_741_824:.2f} GB/s"
    if bps >= 1_048_576:
        return f"{bps / 1_048_576:.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps:.0f} B/s"


def _fmt_eta(sec: float) -> str:
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


# ── yt-dlp logger adapter ─────────────────────────────────────────────────────

class YtdlLogger:
    def __init__(self, write_fn):
        self._write = write_fn

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            return
        self._write(f"[yt-dlp] {msg}")

    def info(self, msg: str) -> None:
        self._write(f"[yt-dlp] {msg}")

    def warning(self, msg: str) -> None:
        self._write(f"[yt-dlp WARN] {msg}")

    def error(self, msg: str) -> None:
        self._write(f"[yt-dlp ERROR] {msg}")


# ── Downloader ────────────────────────────────────────────────────────────────

class Downloader:
    """Runs yt-dlp operations in daemon threads and routes results back to the
    UI thread via *ui_dispatch*.

    Callbacks (all called via ui_dispatch, i.e. on the main thread):
      on_fetch_done(title, meta, thumb_url, video_id, info_dict, success)
      on_progress(pct_float, detail_str, pct_str)
      on_download_done(last_filename_or_None)
      on_download_error(error_message_str)
      on_log_update(text, kind)   — updates the live activity label
    """

    def __init__(self, *, ui_dispatch, write_log,
                 on_fetch_done, on_progress,
                 on_download_done, on_download_error,
                 on_log_update):
        self._ui               = ui_dispatch
        self._write_log        = write_log
        self._on_fetch_done    = on_fetch_done
        self._on_progress      = on_progress
        self._on_download_done = on_download_done
        self._on_download_error = on_download_error
        self._on_log_update    = on_log_update
        self._last_filename: str | None = None

    # ── Fetch ──────────────────────────────────────────────────────────────

    def fetch(self, url: str) -> None:
        """Start a background fetch for *url*."""
        threading.Thread(target=self._do_fetch, args=(url,), daemon=True).start()

    def _do_fetch(self, url: str) -> None:
        self._write_log(f"Fetching info for: {url}")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                    "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
            title     = info.get("title", "Unknown")
            uploader  = info.get("uploader", "")
            duration  = info.get("duration_string", "")
            thumb_url = info.get("thumbnail", "")
            video_id  = info.get("id", "")
            self._write_log(f"Info OK  title={title!r}")
            parts = [p for p in (uploader, duration) if p]
            meta  = "  ·  ".join(parts)
            self._ui(lambda t=title, m=meta, tu=thumb_url, vi=video_id, i=info:
                     self._on_fetch_done(t, m, tu, vi, i, True))
        except Exception as e:
            self._write_log(f"Fetch error: {e}")
            self._ui(lambda msg=str(e):
                     self._on_fetch_done(msg, "", "", "", None, False))

    # ── Download ───────────────────────────────────────────────────────────

    def download(self, url: str, fmt: str, quality: str,
                 save_path: str) -> None:
        """Start a background download."""
        self._last_filename = None
        threading.Thread(target=self._do_download,
                         args=(url, fmt, quality, save_path),
                         daemon=True).start()

    def _do_download(self, url: str, fmt: str, quality: str,
                     save_path: str) -> None:
        self._write_log(f"Download start  url={url}  fmt={fmt}  quality={quality}")
        self._write_log(f"Save path: {save_path}")
        self._write_log(f"ffmpeg: {FFMPEG_PATH or 'NOT FOUND'}")
        self._last_filename = None

        try:
            ydl_fmt, postprocessors = self._build_format(fmt, quality)

            outtmpl = os.path.join(save_path, "%(title)s.%(ext)s")
            self._write_log(f"Format string: {ydl_fmt}")
            self._write_log(f"outtmpl: {outtmpl}")

            ydl_opts = {
                "format":               ydl_fmt,
                "outtmpl":              outtmpl,
                "merge_output_format":  fmt if fmt not in ("mp3", "m4a") else None,
                "progress_hooks":       [self._progress_hook],
                "postprocessor_hooks":  [self._postprocessor_hook],
                "logger":               YtdlLogger(self._write_log),
                "quiet":                False,
                "no_warnings":          False,
                "restrictfilenames":    True,   # prevent path traversal via title
            }
            if FFMPEG_PATH:
                ydl_opts["ffmpeg_location"] = os.path.dirname(FFMPEG_PATH)
            if postprocessors:
                ydl_opts["postprocessors"] = postprocessors

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Extension-swap resolution (muxed output may change extension)
            if self._last_filename and not os.path.isfile(self._last_filename):
                swapped = os.path.splitext(self._last_filename)[0] + f".{fmt}"
                if os.path.isfile(swapped):
                    self._write_log(f"Resolved via extension swap: {swapped}")
                    self._last_filename = swapped

            if self._last_filename:
                self._write_log(
                    f"Final file: {self._last_filename}  "
                    f"exists={os.path.isfile(self._last_filename)}"
                )
            else:
                self._write_log("WARNING: no filename captured")

            fn = self._last_filename
            self._ui(lambda f=fn: self._on_download_done(f))

        except Exception as e:
            self._write_log(f"Download exception: {e}")
            # Step 7 — error recovery: pass a clean message, never re-raise
            msg = str(e).split("\n")[0][:300]
            self._ui(lambda m=msg: self._on_download_error(m))

    # ── Format string builder ──────────────────────────────────────────────

    @staticmethod
    def _build_format(fmt: str, quality: str) -> tuple[str, list]:
        """Return (ydl_format_string, postprocessors_list)."""
        if fmt == "mp3":
            return "bestaudio/best", [
                {"key": "FFmpegExtractAudio",
                 "preferredcodec": "mp3",
                 "preferredquality": "192"}
            ]
        if fmt == "m4a":
            return "bestaudio[ext=m4a]/bestaudio/best", []

        h_map = {"4K": 2160, "1080p": 1080, "720p": 720,
                 "480p": 480, "360p": 360}

        if fmt == "mp4":
            if quality == "4K":
                return (
                    "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]"
                    "/bestvideo[height<=2160]+bestaudio/best"
                ), []
            if quality in h_map:
                h = h_map[quality]
                return (
                    f"bestvideo[vcodec^=avc1][height<={h}][ext=mp4]"
                    f"+bestaudio[ext=m4a]"
                    f"/bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
                    f"/bestvideo[height<={h}]+bestaudio/best"
                ), []
            return (
                "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]"
                "/bestvideo[ext=mp4]+bestaudio[ext=m4a]"
                "/bestvideo+bestaudio/best"
            ), []

        # generic container
        if quality in h_map:
            h = h_map[quality]
            return (
                f"bestvideo[height<={h}][ext={fmt}]+bestaudio"
                f"/bestvideo[height<={h}]+bestaudio/best"
            ), []
        return (
            f"bestvideo[ext={fmt}]+bestaudio/bestvideo+bestaudio/best"
        ), []

    # ── Hooks (called from yt-dlp background thread) ───────────────────────

    def _progress_hook(self, d: dict) -> None:
        if d["status"] == "downloading":
            total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            speed_bps  = d.get("speed")
            eta_sec    = d.get("eta")
            pct = (downloaded / total * 100) if total > 0 else 0
            parts: list[str] = []
            if total > 0:
                parts.append(f"{_fmt_bytes(downloaded)} of {_fmt_bytes(total)}")
            if speed_bps and speed_bps > 0:
                parts.append(_fmt_speed(speed_bps))
            if eta_sec is not None and eta_sec >= 0:
                parts.append(f"{_fmt_eta(eta_sec)} left")
            detail  = "  ·  ".join(parts)
            pct_str = f"{pct:.0f}%"
            self._ui(lambda p=pct, s=detail, ps=pct_str:
                     self._on_progress(p, s, ps))

        elif d["status"] == "finished":
            fname = d.get("filename", "")
            if fname:
                self._last_filename = fname
                self._write_log(f"Fragment finished: {fname}")
            self._ui(lambda: self._on_progress(95, "Merging tracks…", ""))

    def _postprocessor_hook(self, d: dict) -> None:
        if d.get("status") == "finished":
            info = d.get("info_dict", {})
            fp   = info.get("filepath") or info.get("filename", "")
            if fp and os.path.isfile(fp):
                self._last_filename = fp
                self._write_log(f"Post-process output: {fp}")
