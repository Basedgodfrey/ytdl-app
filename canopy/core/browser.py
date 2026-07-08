"""
canopy.core.browser — WKWebView constants, JS bridge, and platform flag.

Only constants and the platform-availability flag live here.
The WKWebView instance lifecycle (embed, animate, poll) is managed by
CanopyApp in ui/main_window.py because it is tightly coupled to the
tkinter root and the thread-safe UI queue.

Supported platforms (paste-link and in-browser button):
  • YouTube  — youtube.com, youtu.be, music.youtube.com
  • Instagram — Posts (/p/), Reels (/reel/, /reels/), IGTV (/tv/)
    Note: private-account content requires being logged in via the browser.
"""

# ── Platform availability ────────────────────────────────────────────────────

try:
    from AppKit import NSApplication, NSMakeRect          # noqa: F401 (re-exported)
    from WebKit import (                                   # noqa: F401
        WKWebView,
        WKWebViewConfiguration,
        WKUserScript,
        WKUserContentController,
    )
    HAS_WKWEBVIEW = True
except Exception:
    HAS_WKWEBVIEW = False

# ── Security: only these URL prefixes may trigger a browser download ──────────
# Paste-link accepts any yt-dlp-supported URL; this list only guards the
# in-browser hash-signal path in _wv_poll().

_ALLOWED_PREFIXES = (
    # YouTube
    "https://www.youtube.com/",
    "https://youtu.be/",
    "https://youtube.com/",
    "https://music.youtube.com/",
    # Instagram — specific media paths only (not profile / explore pages)
    "https://www.instagram.com/p/",
    "https://www.instagram.com/reel/",
    "https://www.instagram.com/reels/",
    "https://www.instagram.com/tv/",
    "https://instagram.com/p/",
    "https://instagram.com/reel/",
    "https://instagram.com/reels/",
    "https://instagram.com/tv/",
)

# ── Inline JS injected into every WKWebView page ────────────────────────────
#
# Adds a floating "Download with Canopy" pill on supported video pages:
#   • YouTube  — watch pages, Shorts
#   • Instagram — Posts (/p/), Reels (/reel/ /reels/), IGTV (/tv/)
# Signals Python by setting location.hash = '#__canopy_dl__:<url>'
# (polled by CanopyApp._wv_poll every 300 ms — no ObjC delegate needed).

WEBVIEW_JS = r"""
(function () {
    'use strict';
    var ACCENT = '#4a7c59';

    /* Store TRUE originals once — re-injection never double-wraps */
    if (!window.__cpwv_orig_push)    window.__cpwv_orig_push    = history.pushState;
    if (!window.__cpwv_orig_replace) window.__cpwv_orig_replace = history.replaceState;

    /* idempotency guard — skip full setup if hooks already live */
    if (window.__cpwv) { if (typeof window.updateDlBtn === 'function') window.updateDlBtn(); return; }
    window.__cpwv = true;

    function _isDownloadablePage(url) {
        /* YouTube watch pages and Shorts */
        if (/[?&]v=/.test(url) || /\/shorts\//.test(url)) return true;
        /* Instagram Posts, IGTV, Reels — require a media ID (≥5 chars) after the path */
        if (/instagram\.com\/(?:[^/?#]+\/)?(?:p|tv|reel|reels?)\/([A-Za-z0-9_-]{5,})/.test(url)) return true;
        return false;
    }

    window.updateDlBtn = function updateDlBtn() {
        var url = location.href;
        var isVideo = _isDownloadablePage(url);
        var btn = document.getElementById('__cpdl');
        if (isVideo && !btn) {
            btn = document.createElement('div');
            btn.id = '__cpdl';
            btn.innerHTML = '⬇︎  Download with Canopy';
            btn.style.cssText =
                'position:fixed;bottom:28px;right:28px;' +
                'background:' + ACCENT + ';color:#fff;' +
                'font-family:-apple-system,BlinkMacSystemFont,sans-serif;' +
                'font-size:13px;font-weight:600;' +
                'padding:11px 22px;border-radius:50px;cursor:pointer;' +
                'z-index:2147483647;user-select:none;' +
                'box-shadow:0 4px 18px rgba(74,124,89,.45);' +
                'transition:transform .15s,box-shadow .15s;';
            btn.onmouseenter = function() {
                btn.style.transform = 'scale(1.05)';
                btn.style.boxShadow = '0 6px 24px rgba(74,124,89,.6)';
            };
            btn.onmouseleave = function() {
                btn.style.transform = '';
                btn.style.boxShadow = '0 4px 18px rgba(74,124,89,.45)';
            };
            btn.onclick = function() {
                /* Use stored original replaceState so our hook doesn't intercept */
                var videoUrl = location.href.split('#')[0];
                try { window.__cpwv_orig_replace.call(history, null, '',
                    '#__canopy_dl__:' + encodeURIComponent(videoUrl)); } catch(e) {}
                btn.innerHTML = '✓  Sent to Canopy';
                btn.style.background = '#3b6d45';
                setTimeout(function() {
                    btn.innerHTML = '⬇︎  Download with Canopy';
                    btn.style.background = ACCENT;
                }, 2000);
            };
            document.body.appendChild(btn);
        } else if (!isVideo && btn) {
            btn.remove();
        }
    };

    /* SPA navigation hooks — always wrap TRUE originals, not prior wrappers */
    history.pushState = function() {
        window.__cpwv_orig_push.apply(this, arguments);
        setTimeout(window.updateDlBtn, 400);
        setTimeout(window.updateDlBtn, 1200);
    };
    history.replaceState = function() {
        window.__cpwv_orig_replace.apply(this, arguments);
        if (!location.hash || !location.hash.startsWith('#__canopy_dl__:'))
            setTimeout(window.updateDlBtn, 400);
    };
    window.addEventListener('popstate', function() { setTimeout(window.updateDlBtn, 300); });

    /* In-page polling fallback for navigations that bypass all hooks */
    var _lh = location.href.split('#')[0];
    setInterval(function() {
        var c = location.href.split('#')[0];
        if (c !== _lh) { _lh = c; setTimeout(window.updateDlBtn, 350); }
    }, 700);

    window.updateDlBtn();
    setTimeout(window.updateDlBtn,  500);
    setTimeout(window.updateDlBtn, 1500);
    setTimeout(window.updateDlBtn, 3000);
})();
"""
