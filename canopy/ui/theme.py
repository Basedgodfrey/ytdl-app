"""
canopy.ui.theme — Legacy shim.

All constants now live in canopy.ui.tokens.
This file re-exports everything so any old import of canopy.ui.theme
continues to work without changes.
"""

from canopy.ui.tokens import *          # noqa: F401, F403
from canopy.ui.tokens import (          # noqa: F401 — explicit for IDE awareness
    SP1, SP2, SP3, SP4,
    FONT_TITLE, FONT_BODY, FONT_LABEL, FONT_CAPTION, FONT_MICRO, FONT_MONO,
    BG, TITLEBAR, CARD, CARD2, BORDER, SEPARATOR,
    ACCENT, ACCENT_HOVER, FG, MUTED, DIM,
    TEXT_PRIMARY, TEXT_MUTED,
    ERROR, SUCCESS,
    PILL_BG, PILL_FG,
    LOG_BG, LOG_GRN, LOG_MUT, LOG_DIM,
    PROG_TRK,
    RADIUS_SM, RADIUS_MD, RADIUS_LG, RADIUS_PILL,
    THUMB_W, THUMB_H, HIST_TW, HIST_TH,
)
