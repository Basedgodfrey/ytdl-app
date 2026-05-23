"""
canopy.ui.browser_panel — Canopy-branded browser nav bar.

BrowserPanel builds the tkinter overlay panel that sits above the
embedded WKWebView.  It is a pure UI widget factory: it takes callback
functions for every action and exposes the resulting widgets so that
CanopyApp can wire the WKWebView navigation to them.

Attributes exposed after construction
--------------------------------------
panel      : tk.Frame   — full-window overlay frame (place()'d by CanopyApp)
nav_h      : int        — total nav height including the 1-px divider
url_entry  : tk.Entry   — the URL text entry (used by _on_wv_nav to sync URL)
url_var    : tk.StringVar
"""

import tkinter as tk
import customtkinter as ctk
from canopy.ui.theme import (
    BG, TITLEBAR, CARD, BORDER, ACCENT, FG, MUTED, DIM, PILL_BG,
)


class BrowserPanel:
    """Build and own the browser overlay panel widgets."""

    _NAV_H = 58   # nav bar height (px); +1 for divider = nav_h

    def __init__(self, root: ctk.CTk, *,
                 on_back, on_forward, on_reload,
                 on_close, on_navigate):
        self._root = root

        # Full-window overlay (plain tk.Frame → clean NSView layer for WKWebView)
        self.panel = tk.Frame(root, bg=BG)

        self._build_nav(on_back, on_forward, on_reload, on_close, on_navigate)

        # Divider between nav bar and web content
        tk.Frame(self.panel, bg=BORDER, height=1).pack(fill="x")

        self.nav_h = self._NAV_H + 1   # +1 for the divider pixel

    # ── Internal build ────────────────────────────────────────────────────────

    def _build_nav(self, on_back, on_forward, on_reload, on_close, on_navigate):
        # Outer tk.Frame — height-locked shell (pack_propagate keeps NSView compat)
        nav_shell = tk.Frame(self.panel, bg=TITLEBAR, height=self._NAV_H)
        nav_shell.pack(fill="x")
        nav_shell.pack_propagate(False)

        # Inner CTkFrame for Canopy-styled content
        nav = ctk.CTkFrame(nav_shell, fg_color=TITLEBAR, corner_radius=0)
        nav.pack(fill="both", expand=True, padx=10, pady=9)

        # ── Icon buttons (CTkButton centres text exactly) ─────────────────────
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

        _icon_btn(nav, "‹", on_back,    size=22).pack(side="left")
        _icon_btn(nav, "›", on_forward, size=22).pack(side="left", padx=(2, 0))
        _icon_btn(nav, "↺", on_reload,  size=16).pack(side="left", padx=(2, 8))

        # ── Close — always right, red × ───────────────────────────────────────
        ctk.CTkButton(
            nav, text="✕", command=on_close,
            font=("Helvetica Neue", 13),
            fg_color="transparent",
            hover_color="#fde8e8",
            text_color="#c0392b",
            corner_radius=8,
            width=36, height=36,
            cursor="hand2",
        ).pack(side="right")

        # ── URL pill ──────────────────────────────────────────────────────────
        url_pill = ctk.CTkFrame(nav, fg_color=CARD, corner_radius=10,
                                border_color=BORDER, border_width=1)
        url_pill.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.url_var = tk.StringVar(value="https://www.youtube.com")
        self.url_entry = tk.Entry(
            url_pill, textvariable=self.url_var,
            bd=0, relief="flat",
            bg=CARD, fg=FG, insertbackground=FG,
            font=("Helvetica Neue", 13),
            highlightthickness=0,
        )
        self.url_entry.pack(side="left", fill="x", expand=True,
                            padx=(12, 0), ipady=5, pady=6)
        self.url_entry.bind("<Return>",
                            lambda e: on_navigate(self.url_var.get()))
        self.url_entry.bind("<FocusIn>",  lambda e: None)
        # FocusOut returns keyboard to WKWebView — wired by CanopyApp
        self._on_navigate = on_navigate

        # Go button inside the pill
        ctk.CTkButton(
            url_pill, text="↵",
            font=("Helvetica Neue", 15),
            fg_color="transparent",
            hover_color=PILL_BG,
            text_color=ACCENT,
            corner_radius=8,
            width=36, height=28,
            cursor="hand2",
            command=lambda: on_navigate(self.url_var.get()),
        ).pack(side="right", padx=(0, 4), pady=4)

    # ── Public helper ─────────────────────────────────────────────────────────

    def update_url(self, url: str) -> None:
        """Sync the URL bar text (called by CanopyApp._on_wv_nav)."""
        self.url_var.set(url)
