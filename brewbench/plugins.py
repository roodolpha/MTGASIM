"""Optional add-ons for your own copy of Brewbench.

Brewbench ships none. If a folder called `plugins` exists in your Brewbench data folder (next to config.json),
each .py file in it is loaded at start-up and its `setup(api)` is called with the small API below. Nothing is
loaded when the folder doesn't exist, which is the case for everyone who hasn't made one.

    def setup(api):
        api.add_route("/my/page", lambda query: (200, "text/html; charset=utf-8", b"<p>hello</p>"))
        api.on_tracker(lambda parser, engine, cards: ...)   # after each read of Arena's log
        api.open_window("Title", "/my/page", width=360, height=240)   # only in the app window build
        api.add_nav("My page", "/my/page")                               # a link in the app's menu

A plugin that raises is skipped and logged; it never stops Brewbench.
"""
import threading
import traceback
from pathlib import Path

ROUTES = {}          # path -> fn(query dict) -> (status, content type, bytes)
NAV = []             # [{"label", "path"}] extra links in the app's menu
TRACKER_HOOKS = []   # fn(parser, engine module, cards)
APP = {"webview": None, "port": None}
_loaded = []
_lock = threading.Lock()


class API:
    def __init__(self, cfg, log, name):
        self.cfg, self._log, self.name = cfg, log, name

    def log(self, msg):
        self._log(f"Plugin {self.name}: {msg}")

    def add_route(self, path, fn):
        ROUTES[path] = fn

    def add_nav(self, label, path):
        """A link in the app's top menu to one of this plugin's pages."""
        NAV.append({"label": label, "path": path})

    def on_tracker(self, fn):
        TRACKER_HOOKS.append(fn)

    def open_window(self, title, path, **kw):
        """A small extra app window showing one of this plugin's pages. Returns the window, or None outside the
        app (the page still works in a browser at http://127.0.0.1:<port><path>)."""
        webview = APP["webview"]
        if webview is None or not APP["port"]:
            return None
        return webview.create_window(title, f"http://127.0.0.1:{APP['port']}{path}", **kw)


def folder(cfg):
    return Path(cfg.home) / "plugins"


def load(cfg, log=print):
    """Load the plugins folder once. Safe to call more than once."""
    with _lock:
        if _loaded:
            return list(_loaded)
        _loaded.append("<checked>")
        d = folder(cfg)
        if not d.is_dir():
            return []
        for f in sorted(d.glob("*.py")):
            ns = {"__name__": f"brewbench_plugin_{f.stem}", "__file__": str(f)}
            try:
                exec(compile(f.read_text(encoding="utf-8"), str(f), "exec"), ns)
                if callable(ns.get("setup")):
                    ns["setup"](API(cfg, log, f.stem))
                _loaded.append(f.stem)
                log(f"Loaded plugin {f.stem}")
            except Exception:
                log(f"Plugin {f.stem} failed to load:\n{traceback.format_exc(limit=3)}")
        return [x for x in _loaded if x != "<checked>"]


def tracker_update(parser, engine, cards):
    for fn in list(TRACKER_HOOKS):
        try:
            fn(parser, engine, cards)
        except Exception:
            pass   # a plugin's mistake mustn't stop the tracker


def route(path, query):
    fn = ROUTES.get(path)
    if fn is None:
        return None
    try:
        return fn(query)
    except Exception as e:
        return 500, "text/plain; charset=utf-8", f"Plugin error: {e!r}".encode()
