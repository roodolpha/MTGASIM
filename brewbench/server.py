"""The local dashboard: a small web server on your own PC (127.0.0.1 only) with a JSON API over your
decks, runs and optimiser results, and a page that shows them. It can also start runs."""
import json
import os
import logging
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, arena_decks, decks as D, formats, gauntlet, runner, stats

log = logging.getLogger("brewbench.server")

PAGE = Path(__file__).resolve().parent / "web" / "dashboard.html"
TRACKER_PAGE = Path(__file__).resolve().parent / "web" / "tracker.html"


class Jobs:
    """Runs started from the dashboard, one at a time (they already use every core you give them)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.history = []

    def start(self, cfg, fmt, deck, opps, games, weighted=False):
        with self.lock:
            if self.current and self.current["state"] in ("running", "stopping"):
                raise RuntimeError("A run is already going. Wait for it to finish or stop it.")
            r = runner.Run(cfg, fmt, deck, opps, games, log=lambda *_: None)
            if weighted:
                r.weights = [D.read_dck(o).weight for o in opps]
            job = {"run": r.id, "label": r.label, "format": fmt.key, "games": games, "done": 0,
                   "state": "running", "started": int(time.time()), "_r": r}
            self.current = job

        def go():
            try:
                r.start(lambda d, t: job.update(done=d))
                job["state"] = "stopped" if r.stopping else "finished"
                if r.missing:
                    job.update(missing=r.missing, problems=r.problems[:6])
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


# sims running outside the app (command line, optimiser), checked in the background every few seconds
_OUTSIDE = {"games": 0, "drivers": 0, "checked": 0}


def _watch_outside(stop_after=None):
    while True:
        try:
            _OUTSIDE.update(runner.find_sims(), checked=time.time())
        except Exception:
            pass
        time.sleep(5)


# "Did this swap help?": the same deck in two versions, on the same seeds, so only the cards differ
SWAP = {"state": "idle"}
_SWAP_RUN = {"r": None}


def deck_changes(a, b):
    """Cards taken out of A and put into B, as [(name, qty)] lists."""
    from collections import Counter as _C
    ca, cb = _C(a.main) + _C({c: 1 for c in a.commanders}), _C(b.main) + _C({c: 1 for c in b.commanders})
    return sorted((ca - cb).items()), sorted((cb - ca).items())


def swap_verdict(p, games):
    """Plain-English reading of a paired comparison where diff = A - B; we report B - A ("the change")."""
    if p.get("diff") is None:
        return {"kind": "none", "text": "Not enough games finished to compare."}
    change, se = -p["diff"], abs(p["diff"] / p["z"]) if p.get("z") else 0
    lo, hi = change - 1.96 * se, change + 1.96 * se
    pts = lambda x: f"{100 * x:+.1f}"
    rng = f"probably between {pts(lo)} and {pts(hi)} points"
    if p["p_value"] is not None and p["p_value"] > 0.95:
        return {"kind": "better", "change": change, "lo": lo, "hi": hi,
                "text": f"The change helped: {pts(change)} points of win rate ({rng})."}
    if p["p_value"] is not None and p["p_value"] < 0.05:
        return {"kind": "worse", "change": change, "lo": lo, "hi": hi,
                "text": f"The change made it worse: {pts(change)} points ({rng})."}
    need = None
    if se and abs(change) >= 0.005:
        import math
        sd = se * math.sqrt(p["n"])
        need = max(0, math.ceil((1.96 * sd / abs(change)) ** 2) - p["n"])
    return {"kind": "unclear", "change": change, "lo": lo, "hi": hi, "more": need,
            "text": f"Too close to call: {pts(change)} points, {rng}."
                    + (f" About {need:,} more games each would settle a gap this size." if need else
                       " Any real difference is small.")}


def start_swap(cfg, fmt, deck_path, list_b, games, opps):
    if SWAP.get("state") == "running":
        raise RuntimeError("A swap test is already running.")
    a = D.read_dck(deck_path)
    b = D.parse_arena(list_b, a.name + " (B)")
    b.format, b.name = a.format, a.name + " (B)"
    if not b.size:
        raise ValueError("Version B has no cards: paste or edit the list.")
    out_, in_ = deck_changes(a, b)
    if not out_ and not in_:
        raise ValueError("Version B is the same as your deck. Change some cards first.")
    folder = cfg.home / "swaps"
    folder.mkdir(parents=True, exist_ok=True)
    pb = b.save(folder / f"{deck_path.stem}-b.dck")
    seed = int(time.time()) % 100000
    SWAP.clear()
    SWAP.update(state="running", phase="A", deck=a.name, format=fmt.key, games=games, done=0, out=out_, into=in_,
                result=None, error=None)

    def go():
        try:
            res = []
            for phase, path, label in (("A", deck_path, a.name), ("B", pb, b.name)):
                SWAP["phase"] = phase
                r = runner.Run(cfg, fmt, path, opps, games, seed=seed, label=label, out_dir=folder / "results",
                               log=lambda *_: None)
                _SWAP_RUN["r"] = r
                res.append(r.start(lambda d, t: SWAP.update(done=d + (games if phase == "B" else 0))))
                if r.stopping:
                    SWAP.update(state="stopped")
                    return
            p = stats.paired(res[0], res[1])
            sa, sb = stats.summary(res[0]), stats.summary(res[1])
            SWAP.update(state="finished", result={"paired": p, "a": sa, "b": sb, "verdict": swap_verdict(p, games)})
        except Exception as e:
            SWAP.update(state="error", error=str(e))
        finally:
            _SWAP_RUN["r"] = None
    threading.Thread(target=go, name="swap-test", daemon=True).start()


# the optimiser, started from the app (one at a time)
OPT = {"state": "idle", "log": []}
_OPT_RUN = {"o": None}


def start_optimiser(cfg, fmt, deck_path, opps, pool, protect, minutes):
    from . import optimiser as O
    if OPT.get("state") == "running":
        raise RuntimeError("The optimiser is already running.")
    if not pool:
        raise ValueError("Add some candidate cards to try.")
    OPT.clear()
    OPT.update(state="running", deck=D.read_dck(deck_path).name, format=fmt.key, log=[], started=int(time.time()),
               error=None, report=None)

    def say(msg):
        OPT["log"] = (OPT["log"] + [str(msg)])[-40:]
    o = O.Optimiser(cfg, fmt, deck_path, opps, pool, protect=protect, log=say)
    _OPT_RUN["o"] = o

    def go():
        try:
            OPT["report"] = o.run(until=time.time() + minutes * 60 if minutes else None)
            OPT["state"] = "stopped" if o.stopping else "finished"
        except Exception as e:
            OPT.update(state="error", error=str(e))
        finally:
            _OPT_RUN["o"] = None
    threading.Thread(target=go, name="optimiser", daemon=True).start()


# building opponent decks takes a while (one EDHREC + Scryfall lookup each), so it runs in the background
GAUNTLET_JOB = {"state": "idle", "format": None, "done": 0, "total": 0, "current": "", "made": [], "skipped": [],
                "error": None}
_GJ_STOP = threading.Event()
_FORGE_NAMES = {}


def forge_names(cfg):
    from . import forge
    try:
        key = str(cfg.forge_dir)
    except Exception:
        raise ValueError("Set up Forge first: Settings > Setup checklist.") from None
    if key not in _FORGE_NAMES:
        names = forge.card_names(cfg.forge_dir)
        if not names:
            raise ValueError("Set up Forge first (Settings > Setup checklist).")
        _FORGE_NAMES[key] = names
    return _FORGE_NAMES[key]


def start_gauntlet_build(cfg, fmt, use_edhrec, limit):
    if GAUNTLET_JOB["state"] == "running":
        return False
    names = forge_names(cfg)
    _GJ_STOP.clear()
    GAUNTLET_JOB.update(state="running", format=fmt.key, done=0, total=0, current="", made=[], skipped=[], error=None)

    def prog(i, n, c):
        GAUNTLET_JOB.update(done=i, total=n, current=c)

    def run():
        try:
            made, skipped = gauntlet.build_faced(cfg, fmt, names, use_edhrec=use_edhrec, limit=limit,
                                                 progress=prog, stop=_GJ_STOP)
            GAUNTLET_JOB.update(state="done", made=made, skipped=skipped)
        except Exception as e:
            GAUNTLET_JOB.update(state="error", error=str(e))
    threading.Thread(target=run, name="gauntlet-build", daemon=True).start()
    return True


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


_RECORD = {"key": None, "data": None}


def deck_records(cfg):
    """How each saved deck has done: on the ladder (from the game tracker) and in sims (from the results folder).
    {deck id: {"ladder": {games, win_rate}, "sim": {games, win_rate}}}. Cached until those files change."""
    tf = cfg.home / "tracker" / "matches.json"
    rd = cfg.results_dir
    key = (tf.stat().st_mtime if tf.exists() else 0, len(list(rd.glob("*.jsonl"))) if rd.exists() else 0,
           max((p.stat().st_mtime for p in rd.glob("*.jsonl")), default=0) if rd.exists() else 0,
           len(list(cfg.decks_dir.glob("*.dck"))))
    if _RECORD["key"] == key:
        return _RECORD["data"]
    decks = {p.stem: D.read_dck(p) for p in cfg.decks_dir.glob("*.dck")}
    by_arena = {d.arena_id: stem for stem, d in decks.items() if d.arena_id}
    by_cmd = {}
    for stem, d in decks.items():
        if d.commanders and not d.arena_id:
            by_cmd.setdefault(d.commanders[0].lower(), stem)
    out = {}

    def add(stem, kind, points, games):
        tot = out.setdefault(stem, {}).setdefault(kind, [0.0, 0])
        tot[0] += points
        tot[1] += games
    try:
        tracked = json.loads(tf.read_text(encoding="utf-8")) if tf.exists() else {}
    except ValueError:
        tracked = {}
    book = None
    for m in (tracked or {}).values():
        if not isinstance(m, dict) or m.get("result") not in ("Win", "Loss", "Draw"):
            continue
        pts = {"Win": 1.0, "Draw": 0.5}.get(m["result"], 0.0)
        dk = m.get("deck") if isinstance(m.get("deck"), dict) else {}
        stem = by_arena.get(dk.get("id"))
        if stem is None and by_cmd:
            from . import cards as C, share
            book = book or C.CardBook(cfg.cache_dir / "cards.json")
            ids = share._ids(m.get("my_commanders"))
            name = D.clean_name(book.name(ids[0]) or "") if ids else ""
            stem = by_cmd.get(name.lower())
        if stem:
            add(stem, "ladder", pts, 1)
    for r in run_list(cfg):
        s = r.get("summary") or {}
        stem = Path(str(r.get("deck") or "")).stem
        if stem in decks and s.get("games"):
            add(stem, "sim", (s.get("win_rate") or 0) * s["games"], s["games"])
    data = {stem: {k: {"games": n, "win_rate": w / n} for k, (w, n) in v.items() if n} for stem, v in out.items()}
    _RECORD.update(key=key, data=data)
    return data


def deck_list(cfg):
    arena_decks.sync_soon(cfg)   # in the background: new Arena decks show up on the next refresh
    out = []
    try:
        rec = deck_records(cfg)
    except Exception as e:
        log.warning("deck records failed: %s", e)
        rec = {}
    for p in sorted(cfg.decks_dir.glob("*.dck")):
        d = D.read_dck(p)
        out.append({"id": p.stem, "name": d.name, "cards": d.total, "main": d.size, "commanders": d.commanders,
                    "ladder": (rec.get(p.stem) or {}).get("ladder"), "sim": (rec.get(p.stem) or {}).get("sim"),
                    "format": d.format, "from_arena": bool(d.arena_id), "list": d.to_arena(),
                    "updated": p.stat().st_mtime})
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
            self._safe(self._get)

        def do_POST(self):
            self._safe(self._post)

        def _safe(self, fn):
            try:
                fn()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except Exception as e:   # never leave the page hanging on an unexpected error
                log.exception("request failed: %s", self.path)
                try:
                    self._send(500, {"error": f"Something went wrong: {e}"})
                except Exception:
                    pass

        def _get(self):
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
            if path == "/api/swap":
                return self._send(200, {k: v for k, v in SWAP.items()})
            if path == "/api/optimiser/status":
                return self._send(200, dict(OPT))
            if path == "/api/gauntlet":
                fk = parse_qs(u.query).get("format", ["brawl"])[0]
                if fk not in formats.FORMATS:
                    return self._send(400, {"error": "unknown format"})
                fmt = formats.get(fk)
                return self._send(200, {"format": fk, "name": fmt.name, "commander": fmt.commander,
                                        "decks": gauntlet.describe(cfg.gauntlet_dir(fk)), "job": GAUNTLET_JOB})
            if path == "/api/share":
                from . import share
                return self._send(200, share.settings(cfg))
            if path == "/api/share/preview":
                from . import share
                try:
                    p = share.build_payload(cfg, bool(cfg.get("share_lists")))
                except Exception as e:
                    return self._send(500, {"error": str(e)})
                return self._send(200, {"matches": len(p["matches"]), "sims": len(p["sims"]), "decks": len(p["decks"]),
                                        "sample": {k: v[:5] for k, v in p.items()}})
            if path == "/api/tracker":
                from . import tracker
                return self._send(200, tracker.STATE)
            if path == "/api/setup":
                from . import setup_wizard
                return self._send(200, setup_wizard.status(cfg))
            if path == "/api/update":
                from . import updates
                return self._send(200, updates.check(force="force" in parse_qs(u.query)))
            if path == "/api/diagnostics":
                return self._send(200, diagnostics_zip(cfg), "application/zip")
            if path == "/api/settings":
                return self._send(200, {k: cfg.get(k) for k in ("ai_profile", "instances", "edhrec")})
            if path == "/api/status":
                return self._send(200, {"version": __version__, "ai": cfg.get("ai_profile", "Default"),
                                        "formats": [{"key": f.key, "name": f.name} for f in formats.FORMATS.values()],
                                        "job": jobs.view(), "outside": {k: _OUTSIDE[k] for k in ("games", "drivers")},
                                        "swap": {k: SWAP.get(k) for k in ("state", "phase", "done", "games", "deck")},
                                        "opt": {"state": OPT.get("state"), "deck": OPT.get("deck"),
                                                "last": (OPT.get("log") or [""])[-1]}})
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

        def _post(self):
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
                    return self._send(200, jobs.start(cfg, fmt, deck, opps, games, weighted=bool(body.get("weighted"))) and jobs.view())
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
            if path == "/api/update/install":
                from . import updates
                if not updates.installed():
                    return self._send(400, {"error": "Only the installed app can update itself. "
                                                     "Running from source? Use git pull."})
                if not updates.install(on_ready_to_quit=ON_QUIT):
                    return self._send(400, {"error": "No newer version to install."})
                return self._send(200, updates.check())
            if path == "/api/app/show":   # a second copy of the app was started: show this one's window
                if ON_SHOW is None:
                    return self._send(200, {"ok": False})
                try:
                    ON_SHOW()
                except Exception:
                    return self._send(200, {"ok": False})
                return self._send(200, {"ok": True})
            if path == "/api/share":
                from . import share
                name = str(body.get("name") or "").strip()
                if name and not re.fullmatch(r"[A-Za-z0-9 _.#-]{3,24}", name):
                    return self._send(400, {"error": "Names are 3-24 letters, numbers, spaces or _ . - #"})
                cfg.data.update(share_name=name or None, share_public=bool(body.get("public")) and bool(name),
                                share_lists=bool(body.get("lists")), share_auto=bool(body.get("auto")))
                cfg.save()
                if body.get("now"):
                    share.share_soon(cfg)
                return self._send(200, share.settings(cfg))
            if path == "/api/share/forget":
                from . import share
                if not share.settings(cfg)["registered"]:
                    return self._send(200, {"ok": True})
                try:
                    share.forget(cfg)
                except Exception as e:
                    return self._send(502, {"error": str(e)})
                return self._send(200, {"ok": True})
            if path == "/api/swap":
                fk = str(body.get("format") or "")
                stem = str(body.get("deck") or "")
                if fk not in formats.FORMATS or not re.fullmatch(r"[A-Za-z0-9_.-]+", stem):
                    return self._send(400, {"error": "Pick a deck and a format."})
                src = cfg.decks_dir / f"{stem}.dck"
                opps = gauntlet.list_decks(cfg.gauntlet_dir(fk))
                if not src.exists():
                    return self._send(400, {"error": "No such deck."})
                if not opps:
                    return self._send(400, {"error": "That format has no opponents yet. Add some on the Decks page."})
                games = max(20, min(5000, int(body.get("games") or 400)))
                try:
                    start_swap(cfg, formats.get(fk), src, str(body.get("list_b") or ""), games, opps)
                except (ValueError, RuntimeError) as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {k: v for k, v in SWAP.items()})
            if path == "/api/optimiser/start":
                fk, stem = str(body.get("format") or ""), str(body.get("deck") or "")
                if fk not in formats.FORMATS or not re.fullmatch(r"[A-Za-z0-9_.-]+", stem):
                    return self._send(400, {"error": "Pick a deck and a format."})
                src = cfg.decks_dir / f"{stem}.dck"
                opps = gauntlet.list_decks(cfg.gauntlet_dir(fk))
                if not src.exists() or not opps:
                    return self._send(400, {"error": "Pick a deck, and add opponents for that format first."})
                lines = lambda k: [D.clean_name(re.sub(r"^\s*\d+\s*x?\s+", "", l)) for l in str(body.get(k) or "").splitlines() if l.strip()]
                try:
                    start_optimiser(cfg, formats.get(fk), src, opps, lines("pool"), lines("protect"),
                                    max(0, int(body.get("minutes") or 0)))
                except (ValueError, RuntimeError) as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, dict(OPT))
            if path == "/api/optimiser/pool":   # quick-fill candidates: cards in your other decks of this format
                stem, fk = str(body.get("deck") or ""), str(body.get("format") or "")
                src = cfg.decks_dir / f"{stem}.dck"
                if not src.exists():
                    return self._send(400, {"error": "No such deck."})
                me = D.read_dck(src)
                have = set(me.main) | set(me.commanders)
                pool = {}
                for p in cfg.decks_dir.glob("*.dck"):
                    if p == src:
                        continue
                    d = D.read_dck(p)
                    if d.format and fk and d.format != fk:
                        continue
                    for n in list(d.main) + list(d.side):
                        if n not in have and n not in D.BASICS and not n.startswith("#"):
                            pool[n] = pool.get(n, 0) + 1
                pool.update({n: pool.get(n, 0) + 1 for n in me.side if n not in have})
                return self._send(200, {"cards": [n for n, _ in sorted(pool.items(), key=lambda x: (-x[1], x[0]))][:120]})
            if path == "/api/stop":   # stops everything: the app's run and any started from the command line
                jobs.stop()
                if _OPT_RUN["o"] is not None:
                    _OPT_RUN["o"].stop()
                if _SWAP_RUN["r"] is not None:
                    _SWAP_RUN["r"].stop()
                n = runner.kill_all_sims()
                _OUTSIDE.update(games=0, drivers=0)
                return self._send(200, {"ok": True, "job": jobs.view(), "ended": n})
            if path.startswith("/api/gauntlet/"):
                fk = str(body.get("format") or "")
                if fk not in formats.FORMATS:
                    return self._send(400, {"error": "unknown format"})
                fmt, folder = formats.get(fk), cfg.gauntlet_dir(fk)
                try:
                    if path == "/api/gauntlet/build":
                        if not fmt.commander:
                            return self._send(400, {"error": "Building from games you've faced works for Brawl formats; "
                                                             "for others, paste lists or copy your decks in."})
                        lim = int(body.get("limit") or 0) or None
                        ok = start_gauntlet_build(cfg, fmt, bool(body.get("edhrec", True)), lim)
                        return self._send(200 if ok else 409, {"job": GAUNTLET_JOB} if ok else {"error": "Already building."})
                    if path == "/api/gauntlet/meta":
                        names = gauntlet.download_meta(cfg, fmt)
                        if not names:
                            return self._send(200, {"added": [], "note": f"Nobody has shared enough {fmt.name} decklists yet. "
                                                    "Tick 'Share my decklists too' in Settings to help get it going."})
                        return self._send(200, {"added": names})
                    if path == "/api/gauntlet/cancel":
                        _GJ_STOP.set()
                        return self._send(200, {"ok": True})
                    if path == "/api/gauntlet/commander":
                        p, d = gauntlet.add_commander(cfg, fmt, str(body.get("commander") or ""), forge_names(cfg),
                                                      use_edhrec=True)
                        return self._send(200, {"id": p.stem, "name": d.name, "cards": d.total})
                    if path == "/api/gauntlet/paste":
                        d = D.parse_arena(str(body.get("list") or ""), str(body.get("name") or "opponent"))
                        if body.get("name"):
                            d.name = str(body["name"])
                        if not d.size:
                            return self._send(400, {"error": "no cards found in that list"})
                        p = d.save(Path(folder) / f"{gauntlet.slug(d.name) or 'opponent'}.dck")
                        return self._send(200, {"id": p.stem, "name": d.name, "cards": d.total})
                    if path == "/api/gauntlet/copy":
                        stem = str(body.get("deck") or "")
                        src = cfg.decks_dir / f"{stem}.dck"
                        if not re.fullmatch(r"[A-Za-z0-9_.-]+", stem) or not src.exists():
                            return self._send(400, {"error": "no such deck"})
                        d = D.read_dck(src)
                        d.arena_id = ""   # a copy, not the synced original
                        p = d.save(Path(folder) / f"{gauntlet.slug(d.name) or stem}.dck")
                        return self._send(200, {"id": p.stem, "name": d.name, "cards": d.total})
                    if path == "/api/gauntlet/remove":
                        stem = str(body.get("id") or "")
                        if stem == "*":
                            n = 0
                            for p in gauntlet.list_decks(folder):
                                p.unlink(); n += 1
                            return self._send(200, {"ok": True, "removed": n})
                        if not re.fullmatch(r"[A-Za-z0-9_.-]+", stem) or stem.startswith("."):
                            return self._send(400, {"error": "bad id"})
                        p = Path(folder) / f"{stem}.dck"
                        if p.exists():
                            p.unlink()
                        return self._send(200, {"ok": True})
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                except Exception as e:   # network trouble etc.: say so instead of dropping the request
                    return self._send(502, {"error": f"That didn't work: {e}"})
                return self._send(404, {"error": "not found"})
            if path == "/api/decks/sync":
                return self._send(200, arena_decks.sync(cfg, force=True))
            if path == "/api/decks/remove":
                stem = str(body.get("id") or "")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", stem) or stem.startswith("."):
                    return self._send(400, {"error": "bad deck id"})
                return self._send(200, {"ok": arena_decks.remove(cfg, stem)})
            if path == "/api/decks":
                text = body.get("list") or ""
                deck = D.parse_arena(text, body.get("name") or "deck")
                if body.get("name"):
                    deck.name = body["name"]
                if not deck.size:
                    return self._send(400, {"error": "no cards found in that list"})
                p = deck.save(cfg.decks_dir / f"{gauntlet.slug(deck.name)}.dck")
                return self._send(200, {"id": p.stem, "cards": deck.total})
            return self._send(404, {"error": "not found"})

    return H


class _Server(ThreadingHTTPServer):
    # never share a port with another program (on Windows SO_REUSEADDR would let us silently steal it)
    # Windows: SO_REUSEADDR would let us silently share a port with another program, so leave it off there.
    # Elsewhere it only allows a quick restart while the old socket is closing, so turn it on.
    allow_reuse_address = os.name != "nt"


ON_SHOW = None   # set by the desktop app: brings its window forward
ON_QUIT = None   # set by the desktop app: closes it (so an update can install over it)
JOBS = None


def serve(cfg, port=8780, open_browser=True, track=True):
    global JOBS
    jobs = JOBS = Jobs()
    threading.Thread(target=_watch_outside, name="sim-watch", daemon=True).start()
    if track:
        from . import tracker
        tracker.start(cfg)
    if cfg.get("share_auto") and cfg.get("share_id"):
        from . import share
        share.share_soon(cfg)   # catch up on games played while the app was closed
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
