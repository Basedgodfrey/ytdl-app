"""
canopy.core.history — Download history persistence.

Storage: ~/Library/Application Support/Canopy/history.json
On first run, migrates from the legacy ~/.ytdl_history.json path automatically.
"""

import os
import json
import shutil

# ── Paths ─────────────────────────────────────────────────────────────────────

HISTORY_DIR  = os.path.expanduser("~/Library/Application Support/Canopy")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")

# Cache / log directories (shared with the rest of the app)
THUMB_CACHE = os.path.expanduser("~/.ytdl_cache/thumbnails")
LOG_FILE    = os.path.expanduser("~/.ytdl_debug.log")
DL_LOGS_DIR = os.path.expanduser("~/.ytdl_cache/logs")

# Legacy path — migrated on first load
_LEGACY_FILE = os.path.expanduser("~/.ytdl_history.json")

_MAX_ENTRIES = 50


# ── Public API ────────────────────────────────────────────────────────────────

def load() -> list:
    """Load history from disk.  Returns a (possibly empty) list of entry dicts.
    Migrates from the legacy ~/.ytdl_history.json on first run if needed."""
    _ensure_dir()
    _migrate_if_needed()
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save(entries: list) -> None:
    """Persist *entries* to disk."""
    _ensure_dir()
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception:
        pass


def append(entries: list, entry: dict) -> list:
    """Prepend *entry*, trim to max length, save and return the updated list."""
    entries = [entry] + [e for e in entries if e is not entry]
    entries = entries[:_MAX_ENTRIES]
    save(entries)
    return entries


def clear(entries: list) -> list:
    """Clear all entries, save and return an empty list."""
    save([])
    return []


# ── Internals ─────────────────────────────────────────────────────────────────

def _ensure_dir() -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)


def _migrate_if_needed() -> None:
    """Copy legacy ~/.ytdl_history.json → new location if the new file is absent."""
    if not os.path.exists(HISTORY_FILE) and os.path.exists(_LEGACY_FILE):
        try:
            _ensure_dir()
            shutil.copy2(_LEGACY_FILE, HISTORY_FILE)
        except Exception:
            pass
