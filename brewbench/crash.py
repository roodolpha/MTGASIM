"""Opt-in crash reports. Nothing is sent unless the user ticks "Send crash reports" in Settings.

A report holds: what went wrong (the error and the code lines it came from), where in Brewbench, the
Brewbench version and the Windows/Mac version, and a random install id (made here, used only to count how
many installs hit the same problem). Folder paths are scrubbed so your user name never leaves the PC.
No Arena data, decks, games, account or sharing key, ever."""
import os
import platform
import re
import secrets
import sys
import threading
import time
import traceback

from . import __version__

_recent = {}          # don't send the same problem more than once an hour per run
_cfg = {"cfg": None}


def setup(cfg):
    _cfg["cfg"] = cfg


def enabled(cfg=None):
    cfg = cfg or _cfg["cfg"]
    return bool(cfg is not None and cfg.get("crash_reports"))


def _install_id(cfg):
    iid = cfg.get("install_id")
    if not iid:
        iid = secrets.token_hex(10)
        cfg.set("install_id", iid)
        cfg.save()
    return iid


def scrub(text):
    """Remove anything that could identify the person: home folder, user name, Windows user paths."""
    text = str(text or "")
    home = os.path.expanduser("~")
    for p in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        if p and len(p) > 3:
            text = text.replace(p, "~")
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user and len(user) > 2:
        text = re.sub(re.escape(user), "<user>", text, flags=re.I)
    text = re.sub(r"(?i)([a-z]:\\users\\)[^\\/\s\"']+", r"\1<user>", text)
    text = re.sub(r"(/(?:home|Users)/)[^/\s\"']+", r"\1<user>", text)
    return text


def report(exc, place="", cfg=None):
    """Send a scrubbed report in the background, if the user opted in. Never raises."""
    try:
        cfg = cfg or _cfg["cfg"]
        if not enabled(cfg):
            return False
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-6000:]
        msg = f"{type(exc).__name__}: {exc}"[:500]
        key = (place, msg)
        if time.time() - _recent.get(key, 0) < 3600:
            return False
        _recent[key] = time.time()
        body = {"install": _install_id(cfg), "version": __version__, "place": str(place)[:80],
                "os": f"{platform.system()} {platform.release()}"[:60], "message": scrub(msg), "trace": scrub(tb)}

        def send():
            try:
                import json
                import urllib.request
                from . import share
                api = (cfg.get("share_api") or share.DEFAULT_API).rstrip("/")
                req = urllib.request.Request(api + "/v1/crash", data=json.dumps(body).encode(), method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "User-Agent": f"Brewbench/{__version__}"})
                urllib.request.urlopen(req, timeout=15).read()
            except Exception:
                pass
        threading.Thread(target=send, name="crash-report", daemon=True).start()
        return True
    except Exception:
        return False


def install_hooks():
    """Report anything that would otherwise crash a thread or the app silently."""
    old = sys.excepthook

    def hook(t, e, tb):
        report(e, "app")
        old(t, e, tb)
    sys.excepthook = hook

    def thook(args):
        if args.exc_type is not SystemExit:
            report(args.exc_value, f"thread {args.thread.name if args.thread else ''}")
    threading.excepthook = thook
