"""
Canopy — YouTube Downloader for macOS
Entry point: imports CanopyApp from the canopy package and launches it.
"""

import os
import sys

# ── SSL certificates (PyInstaller bundles only) ───────────────────────────────
# Frozen apps don't inherit the macOS system CA store and macOS Python builds
# may use Apple SecureTransport, meaning SSL_CERT_FILE alone is ignored.
# We use a two-pronged fix:
#   1. Set SSL_CERT_FILE / REQUESTS_CA_BUNDLE for OpenSSL-backed builds.
#   2. Patch ssl.create_default_context so urllib (and yt-dlp) always loads
#      the right CA bundle regardless of the underlying TLS backend.
if getattr(sys, "frozen", False):
    import ssl as _ssl

    # Prefer macOS system bundle (always current), fall back to bundled certifi
    _cafile: str | None = None
    if os.path.exists("/etc/ssl/cert.pem"):
        _cafile = "/etc/ssl/cert.pem"
    else:
        try:
            import certifi as _certifi
            _cafile = _certifi.where()
        except Exception:
            pass

    if _cafile:
        os.environ["SSL_CERT_FILE"]      = _cafile
        os.environ["REQUESTS_CA_BUNDLE"] = _cafile
        os.environ["CURL_CA_BUNDLE"]     = _cafile

        # Patch ssl.create_default_context so every HTTPS call picks up the certs
        _orig_ssl_ctx = _ssl.create_default_context
        def _ssl_ctx_with_certs(purpose=_ssl.Purpose.SERVER_AUTH, *,
                                cafile=None, capath=None, cadata=None, **kw):
            if cafile is None and capath is None and cadata is None:
                cafile = _cafile
            return _orig_ssl_ctx(purpose, cafile=cafile,
                                 capath=capath, cadata=cadata, **kw)
        _ssl.create_default_context = _ssl_ctx_with_certs

import customtkinter as ctk
from canopy.ui.main_window import CanopyApp

# Keep the project folder's "Date Modified" current on every dev launch
if not getattr(sys, "frozen", False):
    os.utime(os.path.dirname(os.path.abspath(__file__)), None)


def main() -> None:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")
    root = ctk.CTk()
    CanopyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
