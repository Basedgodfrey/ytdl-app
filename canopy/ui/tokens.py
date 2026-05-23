"""
canopy.ui.tokens — Single source of truth for all design tokens.

Import from here in every UI file. No raw hex strings or magic numbers
anywhere else in the UI layer.
"""

# ── Spacing — 8px base grid ───────────────────────────────────────────────────

SP1  = 8
SP2  = 16
SP3  = 24
SP4  = 32

# ── Typography scale ──────────────────────────────────────────────────────────

FONT_TITLE   = ("SF Pro Display",  17, "bold")
FONT_BODY    = ("SF Pro Text",     13, "normal")
FONT_LABEL   = ("SF Pro Text",     11, "normal")
FONT_CAPTION = ("SF Pro Text",     10, "normal")
FONT_MICRO   = ("SF Pro Text",      9, "normal")

# ── Colors ────────────────────────────────────────────────────────────────────

BG           = "#f5f3ee"
CARD         = "#ffffff"
CARD2        = "#f0ede8"
ACCENT       = "#4a7c59"
ACCENT_HOVER = "#3d6b4a"
TEXT_PRIMARY = "#2a2520"
TEXT_MUTED   = "#9e9890"
BORDER       = "#dedad3"
SEPARATOR    = "#e8e4de"
ERROR        = "#c0392b"
SUCCESS      = "#4a7c59"

# ── Geometry ──────────────────────────────────────────────────────────────────

RADIUS_SM    = 8
RADIUS_MD    = 12
RADIUS_LG    = 16
RADIUS_PILL  = 99

# ── Elevation (shadow simulation via border) ──────────────────────────────────

BORDER_DEFAULT  = ("0.5px", BORDER)
BORDER_FOCUS    = ("1px",   ACCENT)

# ── Aliases kept for legacy imports from theme.py ────────────────────────────
# Other modules that still import from theme.py will continue to work;
# but new code should import from tokens.py directly.

TITLEBAR  = "#eeeae2"          # nav bar / title bar background
FG        = TEXT_PRIMARY       # alias
MUTED     = TEXT_MUTED         # alias
DIM       = "#b5b0a8"
PILL_BG   = "#dff0e6"
PILL_FG   = "#3b6d45"
LOG_BG    = "#1a1a18"
LOG_GRN   = "#4ec97b"
LOG_MUT   = "#7a7a70"
LOG_DIM   = "#4a4a42"
LOG_ERR   = "#ff6b6b"
LOG_WARN  = "#f5a623"
LOG_TS    = "#5a5a50"

# Thumbnail placeholder colors (intentional brand colors, not palette tokens)
THUMB_PLACEHOLDER_BG   = "#c8e6d4"
THUMB_PLACEHOLDER_DARK = "#1c1c1e"

# Close-button danger hover
CLOSE_HOVER = "#fde8e8"
PROG_TRK  = "#ece9e3"
FONT_MONO = ("Menlo", 10)
THUMB_W   = 536
THUMB_H   = 220
HIST_TW   = 68
HIST_TH   = 44
