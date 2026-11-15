"""The desktop app entry point (what the Windows installer runs): starts the dashboard and game tracking in the
background and opens the browser. Starting it again while it's running just opens the page."""
import os
import socket
import sys
import time
import webbrowser

from . import server
from .config import Config

PORT = 8780


def _running():
    s = socket.socket()
    try:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


def main():
    cfg = Config()
    url = f"http://127.0.0.1:{PORT}/"
    if _running():
        webbrowser.open(url)
        return 0
    if getattr(sys, "frozen", False) or sys.stdout is None:   # windowed build: no console, log to a file
        logs = cfg.home / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        f = open(logs / "app.log", "a", encoding="utf-8", buffering=1)
        f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} start\n")
        sys.stdout = sys.stderr = f
    no_browser = "--no-browser" in sys.argv or "--background" in sys.argv
    server.serve(cfg, PORT, open_browser=not no_browser, track=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
