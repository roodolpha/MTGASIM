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


class Jobs:
    """Runs started from the dashboard, one at a time (they already use every core you give them)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.history = []

    def start(self, cfg, fmt, deck, opps, games):
        with self.lock:
            if self.current and self.current["state"] == "running":
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
            if self.current and self.current["state"] == "running":
                self.current["_r"].stop()

    def view(self):
        j = self.current
        return {k: v for k, v in j.items() if not k.startswith("_")} if j else None


def run_list(cfg):
    out = []
    rd = cfg.results_dir
    for m in sorted(rd.glob("*.meta.json"), reverse=True)[:200]:
        try:
            meta = json.loads(m.read_text(encoding="utf-8"))
        except ValueError:
            continue
        res = rd / f"{meta['run']}.jsonl"
        s = stats.summary(runner.load_results(res)) if res.exists() else None
        out.append({**meta, "summary": s})
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


def make_handler(cfg, jobs):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            path = u.path.rstrip("/") or "/"
            if path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
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
            if path == "/api/stop":
                jobs.stop()
                return self._send(200, {"ok": True})
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


def serve(cfg, port=8765, open_browser=True):
    jobs = Jobs()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, jobs))
    url = f"http://127.0.0.1:{port}/"
    print(f"Dashboard at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        jobs.stop()
        print("\nStopped.")
