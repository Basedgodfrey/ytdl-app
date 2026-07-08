"""
canopy.core.health — Weekly YouTube / yt-dlp connectivity health check.

Runs in a daemon thread so it never blocks the UI.  Results are persisted
to a JSON file so the interval survives app restarts.

Public API
----------
is_due() -> bool
    True if 7+ days have elapsed since the last check (or no check has run).

run(on_result)
    Start the check in a background thread.  Calls on_result(dict) when done.
    The dict has the shape described in _do_check().

last_result() -> dict | None
    Return the last persisted result dict, or None on first run.
"""

import os
import json
import datetime
import threading
import yt_dlp

# ── Paths ─────────────────────────────────────────────────────────────────────

_DATA_DIR   = os.path.expanduser("~/Library/Application Support/Canopy")
HEALTH_FILE = os.path.join(_DATA_DIR, "health.json")

CHECK_INTERVAL_DAYS = 7

# ── Persistence ───────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        with open(HEALTH_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def is_due() -> bool:
    """Return True if a health check hasn't run in the last 7 days."""
    last = _load().get("last_check")
    if not last:
        return True
    try:
        age = datetime.datetime.now() - datetime.datetime.fromisoformat(last)
        return age.days >= CHECK_INTERVAL_DAYS
    except Exception:
        return True


def last_result() -> dict | None:
    """Return the most recently persisted result, or None."""
    return _load().get("last_result")


def run(on_result) -> None:
    """Start the health check in a daemon thread.

    on_result is called with a results dict once the check finishes.
    It may be called from a non-main thread — the caller must dispatch
    to the UI thread if needed.
    """
    threading.Thread(target=_do_check, args=(on_result,), daemon=True).start()


# ── Core check ────────────────────────────────────────────────────────────────

def _do_check(on_result) -> None:
    """Run connectivity tests and persist + forward the results."""
    now     = datetime.datetime.now()
    results = {
        "checked_at":     now.isoformat(timespec="seconds"),
        "yt_dlp_version": yt_dlp.version.__version__,
        "tests":          {},
    }

    base_opts = {
        "quiet":          True,
        "no_warnings":    True,
        "skip_download":  True,
        "socket_timeout": 20,
    }

    # ── Test 1: regular video ─────────────────────────────────────────────────
    # "Me at the zoo" — the first video ever uploaded; extremely stable.
    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(
                "https://www.youtube.com/watch?v=jNQXAC9IVRw", download=False)
        results["tests"]["video"] = {
            "ok":      True,
            "title":   info.get("title", ""),
            "formats": len(info.get("formats", [])),
        }
    except Exception as exc:
        results["tests"]["video"] = {
            "ok":    False,
            "error": str(exc).split("\n")[0][:200],
        }

    # ── Test 2: Shorts — resolve a live Short via search ─────────────────────
    # Avoids hardcoding a specific ID that may be deleted.
    try:
        search_opts = {**base_opts, "playlist_items": "1"}
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            res = ydl.extract_info(
                "ytsearch1:youtube shorts under 60 seconds", download=False)
        entry     = (res.get("entries") or [res])[0]
        short_url = f"https://www.youtube.com/shorts/{entry['id']}"
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info2 = ydl.extract_info(short_url, download=False)
        results["tests"]["shorts"] = {
            "ok":      True,
            "title":   info2.get("title", ""),
            "formats": len(info2.get("formats", [])),
            "url":     short_url,
        }
    except Exception as exc:
        results["tests"]["shorts"] = {
            "ok":    False,
            "error": str(exc).split("\n")[0][:200],
        }

    # ── Persist ───────────────────────────────────────────────────────────────
    data = _load()
    data["last_check"]  = results["checked_at"]
    data["last_result"] = results
    try:
        _save(data)
    except Exception:
        pass

    on_result(results)
