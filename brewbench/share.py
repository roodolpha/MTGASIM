"""Opt-in sharing with the public site. Nothing is sent unless you run `brewbench share`.

What goes up:
  * your real Arena games from the log: day, format, result, your deck's colours / commander and a hash of
    the list, the opponent's colours / commander as far as you saw them. Never the Arena match id (it's
    hashed with your random uploader id), never your opponent's name, never times finer than the day.
  * your simulator runs, summarised per opponent deck: games, wins, draws, which AI.
  * your decklists, only if you pass --lists.
Your Arena name is never read or sent. You're anonymous unless you pick a display name and --public.
`brewbench share --forget` deletes everything you've sent.
"""
import hashlib
import json
import time
import urllib.error
import urllib.request
from collections import Counter

from . import __version__, arena_log, cards as C, decks as D, runner
from .optimiser import deck_hash

DEFAULT_API = "https://api.brewbench.gg"   # replaced by the real address once the site is live


def event_format(event: str):
    """Arena event names -> our format keys. Unknown events (drafts, specials) aren't shared."""
    e = (event or "").lower()
    if "draft" in e or "sealed" in e or "jumpstart" in e:
        return None
    if "brawl" in e:
        return "standardbrawl" if ("standard" in e or e in ("play_brawl", "brawl")) else "brawl"
    for key in ("historic", "timeless", "alchemy", "explorer"):
        if key in e:
            return None if key == "explorer" else key
    if "ladder" in e or "constructed" in e or e.startswith("play") or "standard" in e:
        return "standard"
    return None


def _colours(names, ident, commander=None):
    if commander and commander in ident:
        return C.colour_string(ident[commander]["ci"])
    letters = set()
    for n in names:
        i = ident.get(n)
        if i and "Land" not in i["type"].split(" // ")[0]:
            letters |= set(i["colors"])
    return C.colour_string(letters)


class Client:
    def __init__(self, cfg, api=None):
        self.cfg = cfg
        self.api = (api or cfg.get("share_api") or DEFAULT_API).rstrip("/")

    def _req(self, method, path, body=None, auth=True):
        headers = {"Content-Type": "application/json", "User-Agent": f"Brewbench/{__version__}"}
        if auth:
            headers["Authorization"] = f"Bearer {self.cfg.get('share_id')}:{self.cfg.get('share_key')}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.api + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode()).get("error")
            except Exception:
                msg = str(e)
            raise RuntimeError(msg) from None

    @property
    def registered(self):
        return bool(self.cfg.get("share_id") and self.cfg.get("share_key"))

    def register(self, name=None, public=False):
        r = self._req("POST", "/v1/register", {"display_name": name, "public": public}, auth=False)
        self.cfg.data.update(share_id=r["client_id"], share_key=r["key"], share_api=self.api,
                             share_name=name, share_public=bool(public and name))
        self.cfg.save()
        return r

    def update(self, name=None, public=False):
        self._req("PATCH", "/v1/me", {"display_name": name, "public": public})
        self.cfg.data.update(share_name=name, share_public=bool(public and name))
        self.cfg.save()

    def forget(self):
        r = self._req("DELETE", "/v1/me")
        for k in ("share_id", "share_key", "share_name", "share_public", "share_sent"):
            self.cfg.data.pop(k, None)
        self.cfg.save()
        return r

    def upload(self, payload):
        out = {"matches": 0, "sims": 0, "decks": 0, "rejected": 0}
        # in chunks, so a big first upload doesn't hit the server's per-request limit
        m, s, d = payload["matches"], payload["sims"], payload["decks"]
        for i in range(0, max(len(m), len(s), len(d), 1), 500):
            r = self._req("POST", "/v1/upload", {"matches": m[i:i + 500], "sims": s[i:i + 500], "decks": d[i:i + 500]})
            for k in out:
                out[k] += r.get(k, 0)
        return out


def build_payload(cfg, include_lists=False, log_paths=None):
    """Everything shareable, from the Arena log and the results folder."""
    salt = cfg.get("share_id") or ""
    book = C.CardBook(cfg.cache_dir / "cards.json")
    matches, decks_out, names = [], {}, set()

    # --- real games
    logs = arena_log.find_logs(cfg.get("arena_log")) if log_paths is None else log_paths
    reader = arena_log.read_all(logs) if logs else arena_log.LogReader()
    # rank before each game comes from the game tracker's history, when it has the game
    ranks = {}
    try:
        tracked = json.loads((cfg.home / "tracker" / "matches.json").read_text(encoding="utf-8"))
        ranks = {k: (v.get("rank_before") or {}).get("class") for k, v in tracked.items()}
    except (OSError, ValueError):
        pass
    raw = []
    for m in reader.matches.values():
        f = event_format(m.event)
        if not f or m.result not in ("Win", "Loss", "Draw") or not m.my_deck:
            continue
        mine = [D.clean_name(book.name(g) or "") for g in m.my_deck]
        cmd = [D.clean_name(book.name(g) or "") for g in m.my_commanders]
        opp = [D.clean_name(book.name(g) or "") for g in m.opp_seen]
        ocmd = [D.clean_name(book.name(g) or "") for g in m.opp_commanders]
        names |= set(mine) | set(cmd) | set(opp) | set(ocmd)
        raw.append((m, f, mine, cmd, opp, ocmd))
    book.save()
    ident = C.identity(sorted(n for n in names if n), cfg.cache_dir / "identity.json")
    for m, f, mine, cmd, opp, ocmd in raw:
        deck = D.Deck(name="x", commanders=[c for c in cmd if c], main=Counter(n for n in mine if n))
        h = deck_hash(deck)
        commander = deck.commanders[0] if deck.commanders else None
        o_commander = next((c for c in ocmd if c), None)
        matches.append({
            "match_key": hashlib.sha256((salt + m.match_id).encode()).hexdigest(),
            "day": time.strftime("%Y-%m-%d", time.gmtime((m.start or 0) / 1000)) if m.start else time.strftime("%Y-%m-%d"),
            "format": f, "event": m.event, "result": m.result, "deck_hash": h,
            "deck_colours": _colours(deck.main, ident, commander), "commander": commander,
            "opp_colours": _colours([n for n in opp if n], ident, o_commander) if opp else None,
            "opp_commander": o_commander,
            "archetype": None if f.endswith("brawl") else C.archetype(deck.main, ident),
            "rank": ranks.get(m.match_id),
        })
        if include_lists:
            decks_out[h] = {"hash": h, "format": f, "colours": matches[-1]["deck_colours"],
                            "commander": commander, "list": deck.to_arena()}

    # --- simulator runs
    sims = []
    rd = cfg.results_dir
    for meta_f in sorted(rd.glob("*.meta.json")):
        try:
            meta = json.loads(meta_f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        res = rd / f"{meta['run']}.jsonl"
        if not res.exists():
            continue
        games = runner.load_results(res)
        try:
            my = D.read_dck(meta["deck"])
        except OSError:
            continue
        opp_decks = {}
        for o in meta.get("opponents", []):
            try:
                opp_decks[o.replace("\\", "/").rsplit("/", 1)[-1]] = D.read_dck(o)
            except OSError:
                pass
        need = set(my.main) | set(my.commanders)
        for od in opp_decks.values():
            need |= set(od.main) | set(od.commanders)
        ident.update(C.identity(sorted(need - set(ident)), cfg.cache_dir / "identity.json"))
        h = deck_hash(my)
        commander = my.commanders[0] if my.commanders else None
        by_opp = {}
        for g in games:
            if g.get("result") not in ("Win", "Loss", "Draw"):
                continue
            k = g.get("deck_b", "?")
            c = by_opp.setdefault(k, [0, 0, 0])
            c[0] += 1
            c[1] += g["result"] == "Win"
            c[2] += g["result"] == "Draw"
        for k, (n, w, d) in by_opp.items():
            od = opp_decks.get(k)
            oc = od.commanders[0] if od and od.commanders else None
            sims.append({
                "run_id": meta["run"], "opp_key": oc or (deck_hash(od) if od else k)[:120],
                "day": time.strftime("%Y-%m-%d", time.gmtime(meta.get("started") or time.time())),
                "format": meta["format"], "ai": meta.get("ai"), "deck_hash": h,
                "deck_colours": _colours(my.main, ident, commander), "commander": commander,
                "opp_colours": _colours(od.main, ident, oc) if od else None, "opp_commander": oc,
                "games": n, "wins": w, "draws": d,
                "archetype": None if meta["format"].endswith("brawl") else C.archetype(my.main, ident),
                "opp_archetype": None if meta["format"].endswith("brawl") or not od else C.archetype(od.main, ident),
            })
        if include_lists:
            decks_out[h] = {"hash": h, "format": meta["format"], "colours": _colours(my.main, ident, commander),
                            "commander": commander, "list": my.to_arena()}
    return {"matches": matches, "sims": sims, "decks": list(decks_out.values())}
