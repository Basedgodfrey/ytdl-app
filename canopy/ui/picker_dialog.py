"""
canopy.ui.picker_dialog — Format / quality picker sheet.

show_picker() presents a modal dialog listing download options and two
optional completion-action checkboxes.  When the user taps a row it calls
on_pick(fmt, quality) and destroys itself; Cancel just destroys it.
"""

import os
import threading

import customtkinter as ctk

from canopy.ui.theme import (
    BG, CARD, BORDER, ACCENT, FG, MUTED, DIM,
)

try:
    from PIL import Image
    _PILLOW = True
except ImportError:
    _PILLOW = False


def show_picker(root: ctk.CTk,
                info: dict,
                thumb_cache: str,
                opt_show_in_folder,   # tk.BooleanVar
                opt_open_when_done,   # tk.BooleanVar
                on_pick) -> None:
    """Open the modal download-options picker.

    Parameters
    ----------
    root                : the CTk root window (used for transient/grab)
    info                : yt-dlp info dict for the current video
    thumb_cache         : path to the thumbnail cache directory
    opt_show_in_folder  : BooleanVar — "Show in Finder when complete"
    opt_open_when_done  : BooleanVar — "Open file when complete"
    on_pick             : callable(fmt: str, quality: str) — invoked on selection
    """
    title    = info.get("title", "Unknown")
    uploader = info.get("uploader", "")
    duration = info.get("duration_string", "")
    video_id = info.get("id", "")

    DIALOG_W = 400
    THUMB_DH = 225

    dlg = ctk.CTkToplevel(root)
    dlg.title("")
    dlg.resizable(False, False)
    dlg.configure(fg_color=CARD)
    dlg.transient(root)
    dlg.grab_set()

    # ── Thumbnail banner ──────────────────────────────────────────────────────
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
        cached = os.path.join(thumb_cache, f"{video_id}.jpg") if video_id else ""
        if cached and os.path.exists(cached) and _PILLOW:
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

    # ── Video info ────────────────────────────────────────────────────────────
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

    # ── Completion-action checkboxes ──────────────────────────────────────────
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
                    variable=opt_show_in_folder,
                    **_cb_kwargs).pack(anchor="w")

    ctk.CTkCheckBox(prefs_inner,
                    text="Open file when complete",
                    variable=opt_open_when_done,
                    **_cb_kwargs).pack(anchor="w", pady=(7, 0))

    ctk.CTkFrame(dlg, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

    # ── Format / quality rows ─────────────────────────────────────────────────
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
            on_pick(f, q)

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

        ctk.CTkFrame(dlg, fg_color=BORDER, height=1,
                     corner_radius=0).pack(fill="x")
        _bind_picker_row(row, _pick)

    # ── Cancel ────────────────────────────────────────────────────────────────
    ctk.CTkButton(dlg, text="Cancel",
                  font=("Helvetica", 12),
                  fg_color=CARD,
                  hover_color="#f0ede8",
                  text_color=MUTED,
                  corner_radius=0,
                  height=48,
                  border_width=0,
                  command=dlg.destroy).pack(fill="x")

    # ── Size + position ───────────────────────────────────────────────────────
    dlg.update_idletasks()
    dh = dlg.winfo_reqheight()
    x  = root.winfo_x() + (root.winfo_width()  - DIALOG_W) // 2
    y  = root.winfo_y() + (root.winfo_height() - dh)        // 2
    dlg.geometry(f"{DIALOG_W}x{dh}+{x}+{y}")


# ── Row interaction helpers ───────────────────────────────────────────────────

def _bind_picker_row(widget, cmd) -> None:
    widget.bind("<Button-1>", lambda e: cmd())
    widget.bind("<Enter>",    lambda e: _row_bg(widget, BG))
    widget.bind("<Leave>",    lambda e: _row_bg(widget, CARD))
    for child in widget.winfo_children():
        _bind_picker_row(child, cmd)


def _row_bg(widget, color: str) -> None:
    try:
        widget.configure(fg_color=color)
    except Exception:
        try:
            widget.configure(bg=color)
        except Exception:
            pass
    for child in widget.winfo_children():
        _row_bg(child, color)
