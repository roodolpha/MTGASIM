"""The local dashboard: a small web server on your own PC (127.0.0.1 only) with a JSON API over your
decks, runs and optimiser results, and a page that shows them. It can also start runs."""
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, decks as D, formats, gauntlet, runner, stats

PAGE = Path(__file__).resolve().parent / "web" / "dashboard.html"
TRACKER_PAGE = Path(__file__).resolve().parent / "web" / "tracker.html"


class Jobs:
    """Runs started from the dashboard, one at a time (they already use every core you give them)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.history = []

    def start(self, cfg, fmt, deck, opps, games):
        with self.lock:
            if self.current and self.current["state"] in ("running", "stopping"):
                raise RuntimeError("A run is already going. Wait for it to finish or stop it.")
            r = runner.Run(cfg, fmt, deck, opps, games, log=lambda *_: None)
            job = {"run": r.id, "label": r.label, "format": fmt.key, "games": games, "done": 0,
                   "state": "running", "started": int(time.time()), "_r": r}
            self.current = job

        def go():
            try:
                r.start(lambda d, t: job.update(done=d))
                job["state"] = "stopped" if r.stopping else "finished"
            except Exception as e:   # surfaced on the page
                job.update(state="error", error=str(e))
            self.history.append({k: v for k, v in job.items() if not k.startswith("_")})

        threading.Thread(target=go, daemon=True).start()
        return job

    def stop(self):
        with self.lock:
            job = self.current
        if job and job["state"] == "running":
            job["state"] = "stopping"
            job["_r"].stop()

    def view(self):
        j = self.current
        return {k: v for k, v in j.items() if not k.startswith("_")} if j else None


_SUMMARIES = {}   # results file -> (mtime, size, summary): big imported runs are only read once


def _summary(path):
    st = path.stat()
    hit = _SUMMARIES.get(path)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    s = stats.summary(runner.load_results(path))
    _SUMMARIES[path] = (st.st_mtime, st.st_size, s)
    return s


def run_list(cfg):
    out = []
    rd = cfg.results_dir
    for m in sorted(rd.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]:
        try:
            meta = json.loads(m.read_text(encoding="utf-8"))
        except ValueError:
            continue
        res = rd / f"{meta['run']}.jsonl"
        s = _summary(res) if res.exists() else None
        out.append({**meta, "summary": s})
    out.sort(key=lambda r: r.get("started") or 0, reverse=True)
    return out


def run_detail(cfg, run_id):
    rd = cfg.results_dir
    meta_f = rd / f"{run_id}.meta.json"
    if not meta_f.exists() or "/" in run_id or "\\" in run_id:
        return None
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    games = runner.load_results(rd / f"{run_id}.jsonl") if (rd / f"{run_id}.jsonl").exists() else []
    pres = stats.card_presence(games)
    cards = sorted(({"card": k, **v} for k, v in pres.items() if v["games_seen"] >= 10),
                   key=lambda r: -r["delta"])
    turns = {}
    for g in games:
        t = g.get("turns") or 0
        if t:
            b = min(30, (t + 1) // 2)   # turns per player
            turns.setdefault(b, [0, 0])
            turns[b][0] += 1
            turns[b][1] += g.get("result") == "Win"
    return {**meta, "summary": stats.summary(games), "opponents": stats.by_opponent(games), "cards": cards,
            "length": [{"turn": k, "games": v[0], "wins": v[1]} for k, v in sorted(turns.items())]}


def deck_list(cfg):
    out = []
    for p in sorted(cfg.decks_dir.glob("*.dck")):
        d = D.read_dck(p)
        out.append({"id": p.stem, "name": d.name, "cards": d.size, "commanders": d.commanders,
                    "list": d.to_arena()})
    return out


def gauntlets(cfg):
    return {f.key: [p.stem for p in gauntlet.list_decks(cfg.gauntlet_dir(f.key))] for f in formats.FORMATS.values()}


def optimiser_list(cfg):
    out = []
    for st in sorted((cfg.home / "optimiser").glob("*/state.json")):
        try:
            s = json.loads(st.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.append({"deck": st.parent.name, "accepted": s.get("accepted", []), "tested": len(s.get("tried", {})),
                    "tried": list(s.get("tried", {}).values())[-30:], "list": s.get("deck")})
    return out


def diagnostics_zip(cfg):
    """Logs and settings for a bug report. Leaves out the sharing key and your Arena account id."""
    import io
    import platform
    import zipfile
    from . import __version__, setup_wizard
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        safe = {k: v for k, v in cfg.data.items() if k not in ("share_key", "share_id")}
        z.writestr("config.json", json.dumps(safe, indent=1))
        info = {"brewbench": __version__, "python": platform.python_version(), "os": platform.platform()}
        try:
            info["setup"] = setup_wizard.status(cfg)
        except Exception as e:
            info["setup_error"] = repr(e)
        z.writestr("system.json", json.dumps(info, indent=1, default=str))
        for f in (cfg.home / "logs").glob("*.log"):
            z.writestr(f"logs/{f.name}", f.read_bytes()[-500_000:])
        t = cfg.home / "tracker" / "tracker.log"
        if t.exists():
            z.writestr("logs/tracker.log", t.read_bytes()[-500_000:])
    return buf.getvalue()


def make_handler(cfg, jobs):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass   # the browser closed the connection early; nothing to do

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if ctype == "application/zip":
                self.send_header("Content-Disposition", 'attachment; filename="brewbench-diagnostics.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            path = u.path.rstrip("/") or "/"
            if path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/tracker":
                from . import tracker
                f = tracker.data_file(cfg)
                data = f.read_text(encoding="utf-8") if f.exists() else '{"matches":[],"cards":{}}'
                page = TRACKER_PAGE.read_text(encoding="utf-8").replace("/*__DATA__*/{}", data.replace("</", "<\\/"))
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/api/tracker":
                from . import tracker
                return self._send(200, tracker.STATE)
            if path == "/api/setup":
                from . import setup_wizard
                return self._send(200, setup_wizard.status(cfg))
            if path == "/api/update":
                from . import setup_wizard
                return self._send(200, setup_wizard.check_update())
            if path == "/api/diagnostics":
                return self._send(200, diagnostics_zip(cfg), "application/zip")
            if path == "/api/settings":
                return self._send(200, {k: cfg.get(k) for k in ("ai_profile", "instances", "edhrec")})
            if path == "/api/status":
                return self._send(200, {"version": __version__, "ai": cfg.get("ai_profile", "Default"),
                                        "formats": [{"key": f.key, "name": f.name} for f in formats.FORMATS.values()],
                                        "job": jobs.view()})
            if path == "/api/runs":
                return self._send(200, run_list(cfg))
            if path.startswith("/api/runs/"):
                d = run_detail(cfg, unquote(path.rsplit("/", 1)[1]))
                return self._send(200 if d else 404, d or {"error": "no such run"})
            if path == "/api/decks":
                return self._send(200, deck_list(cfg))
            if path == "/api/gauntlets":
                return self._send(200, gauntlets(cfg))
            if path == "/api/optimiser":
                return self._send(200, optimiser_list(cfg))
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            # only same-origin pages may start or stop runs
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
                return self._send(403, {"error": "forbidden"})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            path = urlparse(self.path).path.rstrip("/")
            if path == "/api/run":
                try:
                    fmt = formats.get(body.get("format", ""))
                    deck = cfg.decks_dir / f"{gauntlet.slug(body.get('deck', ''))}.dck"
                    if not deck.exists():
                        return self._send(400, {"error": "no such deck"})
                    opps = gauntlet.list_decks(cfg.gauntlet_dir(fmt.key))
                    if not opps:
                        return self._send(400, {"error": f"the {fmt.name} gauntlet is empty"})
                    games = max(1, min(20000, int(body.get("games") or 200)))
                    return self._send(200, jobs.start(cfg, fmt, deck, opps, games) and jobs.view())
                except (ValueError, RuntimeError) as e:
                    return self._send(400, {"error": str(e)})
            if path == "/api/setup/download":
                from . import setup_wizard
                if body.get("what") not in ("java", "forge"):
                    return self._send(400, {"error": "what must be java or forge"})
                setup_wizard.start(cfg, body["what"])
                return self._send(200, {"ok": True})
            if path == "/api/setup/use":
                from . import setup_wizard, forge as F
                try:
                    return self._send(200, setup_wizard.use_existing(cfg, body.get("forge_dir"), body.get("java"),
                                                                     body.get("arena_log")))
                except F.SetupError as e:
                    return self._send(400, {"error": str(e)})
            if path == "/api/settings":
                for k, conv in (("ai_profile", str), ("instances", int), ("edhrec", bool)):
                    if k in body and body[k] not in (None, ""):
                        try:
                            cfg.set(k, conv(body[k]))
                        except (TypeError, ValueError):
                            return self._send(400, {"error": f"bad {k}"})
                return self._send(200, {"ok": True})
            if path == "/api/stop":
                jobs.stop()
                return self._send(200, {"ok": True, "job": jobs.view()})
            if path == "/api/decks":
                text = body.get("list") or ""
                deck = D.parse_arena(text, body.get("name") or "deck")
                if body.get("name"):
                    deck.name = body["name"]
                if not deck.size:
                    return self._send(400, {"error": "no cards found in that list"})
                p = deck.save(cfg.decks_dir / f"{gauntlet.slug(deck.name)}.dck")
                return self._send(200, {"id": p.stem, "cards": deck.size})
            return self._send(404, {"error": "not found"})

    return H


class _Server(ThreadingHTTPServer):
    # never share a port with another program (on Windows SO_REUSEADDR would let us silently steal it)
    allow_reuse_address = False


def serve(cfg, port=8780, open_browser=True, track=True):
    jobs = Jobs()
    if track:
        from . import tracker
        tracker.start(cfg)
    try:
        httpd = _Server(("127.0.0.1", port), make_handler(cfg, jobs))
    except OSError:
        raise SystemExit(f"Port {port} is already in use (the dashboard may already be open: try http://127.0.0.1:{port}/). "
                         f"Or pick another with: brewbench serve --port <number>")
    url = f"http://127.0.0.1:{port}/"
    print(f"Dashboard at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        jobs.stop()
        print("\nStopped.")
