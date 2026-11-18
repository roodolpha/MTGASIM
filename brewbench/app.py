"""The desktop app (what the Windows installer runs).

Brewbench opens in its own window (Windows' built-in WebView2 engine, via pywebview) with an icon in the
system tray. Closing the window tucks it into the tray so your Arena games keep being recorded; Quit in the
tray menu stops it. Starting it again while it's running brings the existing window back.

Under the hood the window shows a small local page served on 127.0.0.1 only; nobody else can reach it.
If the window can't be created (no WebView2 on the PC), it falls back to opening that page in the browser.

  brewbench.exe               open the app
  brewbench.exe --background  start in the tray only (used for "Start with Windows")
  brewbench.exe --selftest    check the bundled pieces load, then exit (used by the release build)
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

from . import __version__, server
from .config import Config

PORT = 8780
URL = f"http://127.0.0.1:{PORT}/"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Brewbench"
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "icon.png")


# ---------------------------------------------------------------- one copy at a time
def _running():
    s = socket.socket()
    try:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


def _ask_running_copy_to_show():
    try:
        req = urllib.request.Request(URL + "api/app/show", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception:
        return False


def _wait_for_server(timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if _running():
            return True
        time.sleep(0.15)
    return False


# ---------------------------------------------------------------- start with Windows (HKCU Run key)
def _exe_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --background'
    return f'"{sys.executable}" -m brewbench app --background'


def startup_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except Exception:
        return False


def set_startup(on):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _exe_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- the app
class App:
    def __init__(self, cfg, background=False):
        self.cfg = cfg
        self.background = background
        self.window = None
        self.tray = None
        self.quitting = False
        self.told_about_tray = bool(cfg.get("told_about_tray"))

    # window
    def show(self):
        if self.window is None:
            webbrowser.open(URL)
            return
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass

    def _on_closing(self):
        if self.quitting:
            return True
        if self.tray is None:     # no tray (Mac): closing the window quits, like most Mac apps' last window
            self.quitting = True
            threading.Thread(target=self.quit, daemon=True).start()
            return True
        self.window.hide()   # keep running in the tray
        if not self.told_about_tray and self.tray is not None:
            self.told_about_tray = True
            self.cfg.set("told_about_tray", True)
            self.cfg.save()
            try:
                self.tray.notify("Brewbench is still running in the tray and recording your Arena games. "
                                 "Right-click the icon to quit.", "Brewbench")
            except Exception:
                pass
        return False

    def quit(self):
        self.quitting = True
        try:
            if server.JOBS is not None:
                server.JOBS.stop()   # don't leave Java sims running after the app has gone
        except Exception:
            pass
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:
            pass
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:
            pass
        os._exit(0)   # the server and tracker threads are daemons; make sure nothing lingers

    def check_updates(self, force=False, always_say=False):
        from . import updates
        info = updates.check(force=force)
        if self.tray is None:
            return info
        try:
            if info["newer"] and (always_say or self.cfg.get("update_told") != info["latest"]):
                self.cfg.set("update_told", info["latest"])
                self.cfg.save()
                self.tray.notify(f"Brewbench {info['latest']} is out. Open Brewbench and click Update now.", "Update available")
            elif always_say and not info["newer"]:
                self.tray.notify(f"You're on the latest version ({info['current']})." if info["latest"]
                                 else "Couldn't check for updates right now.", "Brewbench")
        except Exception:
            pass
        return info

    def _update_loop(self):
        time.sleep(20)   # let the window and tracker settle first
        while not self.quitting:
            self.check_updates()
            time.sleep(6 * 3600)

    def stop_sims(self):
        from . import runner
        try:
            if server.JOBS is not None:
                server.JOBS.stop()
            n = runner.kill_all_sims()
            if self.tray is not None:
                self.tray.notify("Stopped all sims. Games already played are kept." if n or server.JOBS
                                 else "No sims were running.", "Brewbench")
        except Exception:
            pass

    # tray
    def start_tray(self):
        if sys.platform == "darwin":
            # on macOS the tray and the window both need the main thread; the window wins
            return
        try:
            import pystray
            from PIL import Image
        except Exception as e:
            print(f"No tray icon ({e!r})")
            return
        menu = pystray.Menu(
            pystray.MenuItem("Open Brewbench", lambda: self.show(), default=True),
            pystray.MenuItem("Stop all sims", lambda: self.stop_sims()),
            pystray.MenuItem("Check for updates", lambda: self.check_updates(force=True, always_say=True)),
            pystray.MenuItem("Start with Windows", lambda: set_startup(not startup_enabled()),
                             checked=lambda item: startup_enabled(), visible=sys.platform == "win32"),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self.quit()),
        )
        self.tray = pystray.Icon("brewbench", Image.open(ICON), f"Brewbench {__version__}", menu)
        self.tray.run_detached()

    def run(self):
        server.ON_SHOW = self.show
        server.ON_QUIT = self.quit
        self.start_tray()
        threading.Thread(target=self._update_loop, name="update-check", daemon=True).start()
        try:
            import webview
        except Exception as e:   # no pywebview / no WebView2: the browser still works
            print(f"No app window ({e!r}); opening the browser instead.")
            if not self.background:
                webbrowser.open(URL)
            threading.Event().wait()   # the tray (or Ctrl+C) ends it
            return
        try:
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        except Exception:
            pass
        self.window = webview.create_window(
            "Brewbench", URL, width=1360, height=900, min_size=(900, 600),
            background_color="#0F0F10", hidden=self.background, text_select=True)
        self.window.events.closing += self._on_closing
        from . import plugins
        plugins.APP["webview"] = webview   # lets your own add-ons open a small window
        webview.start(private_mode=False, storage_path=str(self.cfg.home / "webview"))
        # webview.start returns when the last window is destroyed
        self.quit()


def _log_to_file(cfg):
    logs = cfg.home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    f = open(logs / "app.log", "a", encoding="utf-8", buffering=1)
    f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} start {__version__}\n")
    sys.stdout = sys.stderr = f


def selftest():
    """Checks the frozen build has everything it needs. Exit code 0 = fine."""
    problems = []
    for mod in ("webview", "PIL.Image") + (() if sys.platform == "darwin" else ("pystray",)):
        try:
            __import__(mod)
        except Exception as e:
            problems.append(f"{mod}: {e!r}")
    if not os.path.exists(ICON):
        problems.append("icon.png missing")
    for page in ("dashboard.html", "tracker.html"):
        if not os.path.exists(os.path.join(os.path.dirname(ICON), page)):
            problems.append(f"{page} missing")
    print("\n".join(problems) or f"Brewbench {__version__} selftest OK")
    return 1 if problems else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    background = "--background" in argv or "--no-browser" in argv
    if "--after-update" in argv:
        # reopened by the installer: the old copy may still be closing, so give it time rather than
        # mistaking it for a running copy and quitting (which left nothing open after an update)
        for _ in range(60):
            if not _running():
                break
            time.sleep(0.5)
    if _running():
        # already open: bring that window forward (or, for an old version without the window, open the page)
        if not background and not _ask_running_copy_to_show():
            webbrowser.open(URL)
        return 0
    cfg = Config()
    if getattr(sys, "frozen", False) or sys.stdout is None:   # windowed build: no console, log to a file
        _log_to_file(cfg)
    from . import crash
    crash.setup(cfg)
    crash.install_hooks()
    threading.Thread(target=server.serve, args=(cfg, PORT), kwargs={"open_browser": False, "track": True},
                     name="brewbench-server", daemon=True).start()
    if not _wait_for_server():
        print("The local server didn't start (is port 8780 taken by something else?)")
        return 1
    App(cfg, background).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
