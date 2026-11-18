"""Watches Arena's Player.log and keeps your game history and dashboard stats up to date.

Runs inside `brewbench serve` (or on its own with `brewbench track`). Data lives in ~/.brewbench/tracker:
matches.json (every game), decks.json (every deck version), wildcards.json, upgrades.json (your plan),
dashboard_data.json (what the dashboard reads)."""
import os
import shutil
import threading
import time
from pathlib import Path

STATE = {"status": "not started", "games": 0, "last": None, "error": None}


def _engine(cfg):
    os.environ["BREWBENCH_TRACKER_DIR"] = str(cfg.home / "tracker")
    from . import tracker_engine as E
    log_path = cfg.get("arena_log")
    if log_path:
        E.LOG = log_path
        E.PREV_LOG = str(Path(log_path).with_name("Player-prev.log"))
    elif not os.path.exists(E.LOG):
        mac = Path.home() / "Library" / "Logs" / "Wizards Of The Coast" / "MTGA"
        if (mac / "Player.log").exists():
            E.LOG, E.PREV_LOG = str(mac / "Player.log"), str(mac / "Player-prev.log")
    return E


def import_old_tracker(cfg, src):
    """Copy an Arena Tracker folder's history (matches, decks, wildcards, plan, card cache) into Brewbench."""
    dst = cfg.home / "tracker"
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for f in ("matches.json", "decks.json", "wildcards.json", "upgrades.json", "card_cache.json", "craft.json"):
        s = Path(src) / f
        if s.exists():
            shutil.copyfile(s, dst / f)
            copied.append(f)
    old_cfg = Path(src) / "config.json"
    if old_cfg.exists():
        import json
        c = json.loads(old_cfg.read_text(encoding="utf-8"))
        keep = {k: c[k] for k in ("my_user_id", "last_rank") if k in c}
        (dst / "config.json").write_text(json.dumps(keep), encoding="utf-8")
        copied.append("config.json (your Arena account id and rank)")
    return copied


def rebuild(cfg):
    E = _engine(cfg)
    store = E.load_json(E.MATCHES_FILE, {})
    cards = E.Cards()
    E.build_outputs(store, cards)
    return len(store)


def run(cfg, log=print, stop=None):
    """Import what's in the log now, then keep watching. Blocks; run it in a thread."""
    E = _engine(cfg)
    E.log = lambda msg: (log(f"Tracker: {msg}"), STATE.update(last=msg))
    try:
        while not os.path.exists(E.LOG):
            STATE["status"] = "waiting for Arena's log (turn on Detailed Logs in Arena's settings)"
            if stop and stop.wait(30):
                return
        store = E.load_json(E.MATCHES_FILE, {})
        config = E.load_json(E.CONFIG_FILE, {})
        cards = E.Cards()
        parser = E.MatchParser(store, config)
        before = len(store)
        STATE["status"] = "reading the log"
        if os.path.exists(E.PREV_LOG):
            E.read_file(E.PREV_LOG, parser)
            parser.cur = None
        pos = E.read_file(E.LOG, parser)
        parser.live = True
        if parser.pending_inv:
            parser.record_inventory(parser.pending_inv, int(time.time() * 1000))
        E.learn_my_user_id(store, config)
        E.save_json(E.MATCHES_FILE, store)
        E.save_json(E.CONFIG_FILE, config)
        E.build_outputs(store, cards)
        STATE.update(status="watching", games=len(store))
        from . import plugins
        log(f"Tracker: {len(store)} games on record ({len(store) - before} new from the log).")
        size = E._log_size()
        while not (stop and stop.wait(E.POLL_SECONDS)):
            try:
                new_size = E._log_size()
            except OSError:
                continue
            if new_size < size:   # Arena restarted with a fresh log
                pos, parser.cur = 0, None
            size = new_size
            if new_size <= pos:
                continue
            parser.new_match = False
            try:
                pos = E.read_file(E.LOG, parser, pos)
            except OSError:
                continue
            except Exception as e:
                E.log(f"Skipped unreadable log section: {e!r}")
                pos, parser.cur = os.path.getsize(E.LOG), None
                continue
            STATE["in_game"] = parser.cur is not None
            plugins.tracker_update(parser, E, cards)
            if parser.new_match:
                E.learn_my_user_id(store, config)
                E.save_json(E.MATCHES_FILE, store)
                E.save_json(E.CONFIG_FILE, config)
                E.build_outputs(store, cards)
                STATE["games"] = len(store)
                if store:
                    last = max(store.values(), key=lambda m: m.get("end") or 0)
                    log(f"Tracker: saved a {last['result']} ({last['turns']} turns).")
                if cfg.get("share_auto") and cfg.get("share_id"):
                    from . import share
                    share.share_soon(cfg)
    except Exception as e:
        STATE.update(status="stopped by an error", error=repr(e))
        from . import crash
        crash.report(e, "game tracker")
        log(f"Tracker stopped: {e!r}")


def start(cfg, log=print):
    stop = threading.Event()
    threading.Thread(target=run, args=(cfg, log, stop), daemon=True).start()
    return stop


def data_file(cfg):
    return cfg.home / "tracker" / "dashboard_data.json"


def in_game():
    return bool(STATE.get("in_game"))
