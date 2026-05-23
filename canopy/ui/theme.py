"""
canopy.ui.theme — Colour palette, typography, and size constants.

Import this module anywhere a UI file needs access to the design tokens.
No tkinter or CTk imports here — pure Python literals only.
"""

# ── Colour palette ────────────────────────────────────────────────────────────

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

# ── Typography ────────────────────────────────────────────────────────────────

FONT_MONO = ("Menlo", 10)

# ── Thumbnail sizes ───────────────────────────────────────────────────────────

THUMB_W  = 536   # main info-card banner width  (px, logical)
THUMB_H  = 220   # main info-card banner height (px, logical)

HIST_TW  = 68    # history-row thumbnail width
HIST_TH  = 44    # history-row thumbnail height
