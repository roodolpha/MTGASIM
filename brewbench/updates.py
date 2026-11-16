"""Keeping the installed app up to date.

The website publishes latest.json (version, installer address, what's new). The app reads it at start and every
few hours. "Update now" downloads that installer and runs it silently; the installer closes Brewbench, replaces
it, and opens the new version. Running from source (not the installed app) only reports that an update exists.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from . import __version__

LATEST_URL = os.environ.get("BREWBENCH_LATEST_URL") or "https://mtgasim.roododger.workers.dev/latest.json"
CHECK_EVERY = 6 * 3600

_state = {"checked": 0, "info": None, "install": {"state": "idle", "done": 0, "total": 0, "error": None}}
_lock = threading.Lock()


def vtuple(v):
    out = []
    for part in str(v or "0").lstrip("v").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def installed():
    """True for the installed Windows app (the only build that can update itself)."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def check(force=False, url=None):
    """{"current", "latest", "newer", "url", "page", "notes", "can_install", "install"}. Cached for 6 hours;
    never raises (no network just means no news)."""
    with _lock:
        fresh = time.time() - _state["checked"] < CHECK_EVERY
        if force or not fresh or _state["info"] is None:
            info = None
            try:
                req = urllib.request.Request(url or LATEST_URL, headers={"User-Agent": f"Brewbench/{__version__}",
                                                                         "Cache-Control": "no-cache"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    info = json.loads(r.read().decode())
            except Exception:
                info = None
            _state["checked"] = time.time()
            _state["info"] = info if isinstance(info, dict) else {}
        info = _state["info"] or {}
    latest = str(info.get("version") or "").lstrip("v") or None
    return {"current": __version__, "latest": latest,
            "newer": bool(latest) and vtuple(latest) > vtuple(__version__),
            "url": info.get("url"), "page": info.get("page"), "notes": str(info.get("notes") or "")[:2000],
            "can_install": installed(), "install": dict(_state["install"])}


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": f"Brewbench/{__version__}"})
    st = _state["install"]
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        st["total"] = int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            st["done"] += len(chunk)
    with open(dest, "rb") as f:
        if f.read(2) != b"MZ" or os.path.getsize(dest) < 1_000_000:
            raise RuntimeError("the download wasn't a Windows installer")


def install(on_ready_to_quit=None):
    """Downloads the newest installer and starts it silently, in the background. The installer closes this
    app, installs over it and starts the new version. Returns False if it can't (not installed / nothing new)."""
    info = check()
    if not (info["newer"] and info["url"] and installed()):
        return False
    st = _state["install"]
    if st["state"] in ("downloading", "starting"):
        return True
    st.update(state="downloading", done=0, total=0, error=None)

    def run():
        try:
            folder = os.path.join(tempfile.gettempdir(), "brewbench-update")
            os.makedirs(folder, exist_ok=True)
            dest = os.path.join(folder, f"brewbench-setup-{info['latest']}.exe")
            _download(info["url"], dest)
            st["state"] = "starting"
            # /UPDATE tells the installer to reopen Brewbench when it's done
            subprocess.Popen([dest, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE"],
                             close_fds=True, creationflags=0x00000008 | 0x00000200)   # detached, new group
            if on_ready_to_quit:
                threading.Timer(1.5, on_ready_to_quit).start()
        except Exception as e:
            st.update(state="error", error=str(e))
    threading.Thread(target=run, name="brewbench-update", daemon=True).start()
    return True
