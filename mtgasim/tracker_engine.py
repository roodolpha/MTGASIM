"""Game tracking for MTGASIM: reads MTG Arena's Player.log and keeps a detailed record of every game you play
(per-turn life, board, hand, plays, draws, removals, damage, combat), then works out the stats the dashboard shows.

Ported from the author's private Arena Tracker, minus everything that predicts or advises during a game.
MTGASIM only reads the log: no overlay, no memory reading, no input to the game.
"""
import csv
import glob
import sqlite3
import urllib.parse
import json
import math
import os
import pathlib
import re
import socket
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime

VERSION = 3
HERE = os.environ.get("MTGASIM_TRACKER_DIR") or os.path.join(os.path.expanduser("~"), ".mtgasim", "tracker")
os.makedirs(HERE, exist_ok=True)
LOG_DIR = os.environ.get("ARENA_LOG_DIR") or os.path.join(
    os.path.expanduser("~"), "AppData", "LocalLow", "Wizards Of The Coast", "MTGA")
LOG = os.path.join(LOG_DIR, "Player.log")
PREV_LOG = os.path.join(LOG_DIR, "Player-prev.log")
MATCHES_FILE = os.path.join(HERE, "matches.json")
CACHE_FILE = os.path.join(HERE, "card_cache.json")
CONFIG_FILE = os.path.join(HERE, "config.json")
DATA_FILE = os.path.join(HERE, "dashboard_data.json")
CSV_FILE = os.path.join(HERE, "matches.csv")
WILDCARDS_FILE = os.path.join(HERE, "wildcards.json")
COLLECTION_FILE = os.path.join(HERE, "collection.json")
DAEMON_EXE = os.path.join(HERE, "daemon", "bin", "mtga-tracker-daemon.exe")
DAEMON_URL = "http://localhost:6842"
DAEMON_PROC = {"p": None}
NN_HIST_FILE = os.path.join(HERE, "nn_history.json")
SIM_DIR = os.path.join(HERE, "sim")
SIM_SETTINGS = os.path.join(SIM_DIR, "settings.json")
SIM = {"m": None, "decks_busy": False, "decks": {}}
SIM_RETRAIN_EVERY = 150   # simulated games between retrains
SIM_TRAIN_MAX = 6000      # most recent simulated games used for training
UPGRADES_FILE = os.path.join(HERE, "upgrades.json")
DECKS_FILE = os.path.join(HERE, "decks.json")
TRACKER_LOG = os.path.join(HERE, "tracker.log")
STOP_FLAG = os.path.join(HERE, "stop.flag")
OVERLAY_OFF = os.path.join(HERE, "overlay_off.flag")
HISTORY_OFF = os.path.join(HERE, "overlay_history_off.flag")
MULL_OFF = os.path.join(HERE, "mulligan_advice_off.flag")
SHOW_SIDE = os.path.join(HERE, "show_overlay.flag")
FEEDBACK_FILE = os.path.join(HERE, "feedback.json")
MODEL_FILE = os.path.join(HERE, "winmodel.json")
CARD_MODEL_FILE = os.path.join(HERE, "card_model.json")
NN_FILE = os.path.join(HERE, "nn_model.json")
NN_FILES = {"current": NN_FILE, "goal": os.path.join(HERE, "nn_goal.json"), "draft": os.path.join(HERE, "nn_draft.json")}
GOAL_DECK_FILE = os.path.join(HERE, "goal_deck.json")
LIMITED_FILE = os.path.join(HERE, "limited_games.json")   # your draft / sealed games (kept out of the Brawl stats)
DRAFT = {}   # {"a": DraftAssistant} once the tracker is running


def is_limited_event(event):
    return any(k in (event or "") for k in ("Draft", "Sealed"))
RAW_REVEALS = os.path.join(HERE, "raw_reveals.jsonl")   # Arena messages about revealed cards, kept to check the parsing
RAW_REVEALS_MAX = 5 * 1024 * 1024
NETPICK_OFF = os.path.join(HERE, "net_pick_off.flag")
EDH_FILE = os.path.join(HERE, "edhrec_cache.json")
PREDICT_OFF = os.path.join(HERE, "predictions_off.flag")
REC_DIR = os.path.join(HERE, "recordings")
REC_OFF = os.path.join(HERE, "recording_off.flag")
CLIP_DIR = os.path.join(REC_DIR, "clips")
CLIPS_OFF = os.path.join(HERE, "clips_off.flag")
LOCAL_PORT = 8766  # dashboard + feedback API on this PC only
POLL_SECONDS = 3
ARENA_CHECK_SECONDS = 5
LOCK_PORT = 47391  # stops two copies of the tracker running at once
REMOVAL = {"Destroy": "Destroyed", "Exile": "Exiled", "Sacrifice": "Sacrificed",
           "SBA_Damage": "Died to damage", "SBA_Deathtouch": "Died to deathtouch",
           "SBA_ZeroToughness": "Shrunk to 0 toughness", "Return": "Bounced to hand",
           "SBA_LegendRule": "Legend rule", "Put": "Put elsewhere", "Discard": "Discarded"}

TRACKED_EVENTS = None  # None = every constructed event; config.json "track_events" can limit it
OTHER_FILE = os.path.join(HERE, "other_games.json")
EVENT_NAMES = {
    "Brawl_Ladder": "Competitive Brawl",
    "Play_Brawl_Historic": "Brawl",
    "Play_Brawl": "Standard Brawl",
    "Ladder": "Standard Ranked",
    "Traditional_Ladder": "Standard Ranked Bo3",
    "Historic_Ladder": "Historic Ranked",
    "Traditional_Historic_Ladder": "Historic Ranked Bo3",
    "Alchemy_Ladder": "Alchemy Ranked",
    "Traditional_Alchemy_Ladder": "Alchemy Ranked Bo3",
    "Timeless_Ladder": "Timeless Ranked",
    "Traditional_Timeless_Ladder": "Timeless Ranked Bo3",
    "Explorer_Ladder": "Pioneer Ranked",
    "Traditional_Explorer_Ladder": "Pioneer Ranked Bo3",
    "Play": "Standard Play",
    "Traditional_Play": "Standard Play Bo3",
    "Historic_Play": "Historic Play",
    "DirectGame": "Direct Challenge",
}
GUILDS = {"W": "Mono-White", "U": "Mono-Blue", "B": "Mono-Black", "R": "Mono-Red", "G": "Mono-Green", "C": "Colourless",
          "WU": "Azorius", "UB": "Dimir", "BR": "Rakdos", "RG": "Gruul", "WG": "Selesnya", "WB": "Orzhov",
          "UR": "Izzet", "BG": "Golgari", "WR": "Boros", "UG": "Simic", "WUB": "Esper", "UBR": "Grixis",
          "BRG": "Jund", "WRG": "Naya", "WUG": "Bant", "WBG": "Abzan", "WUR": "Jeskai", "UBG": "Sultai",
          "WBR": "Mardu", "URG": "Temur", "WUBRG": "Five-colour"}


# ------------------------------------------------------------------ storage
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    for attempt in range(40):   # Windows refuses the swap while another process (e.g. training) is reading the file
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.5)


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:  # started from a CMD window: keep the log file up to date as well
        if os.path.abspath(getattr(sys.stdout, "name", "") or "x") != os.path.abspath(TRACKER_LOG):
            with open(TRACKER_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ card roles
RAMP_RE = re.compile(r"add \{[wubrgc]\}|add one mana|add (two|three) mana|search your library for (up to (one|two) )?(a )?basic land"
                     r"|put (a|up to one) land card|search your library for (a|up to one) land")
INTERACT_RE = re.compile(r"counter target|destroy target|exile target|return target (nonland )?(creature|permanent|spell)"
                         r"|return all|deals damage equal to its power to|fights|loses all abilities|becomes a 3/3"
                         r"|deals \d+ damage to (any target|target creature)|destroy all|return each")
DRAW_RE = re.compile(r"draws? (a|one|two|three|four|x|that many) cards?|draw cards equal")


def card_roles(info):
    t, o = info.get("type", ""), (info.get("oracle") or "").lower()
    roles = []
    if "Land" in t and "Creature" not in t:
        return ["land"]
    if RAMP_RE.search(o):
        roles.append("ramp")
    if INTERACT_RE.search(o):
        roles.append("interaction")
    if DRAW_RE.search(o):
        roles.append("draw")
    if "Creature" in t:
        roles.append("creature")
    return roles


def scry_info(d):
    face = (d.get("card_faces") or [{}])[0]
    imgs = d.get("image_uris") or face.get("image_uris") or {}
    oracle = d.get("oracle_text") or " // ".join(f.get("oracle_text", "") for f in d.get("card_faces") or [])
    info = {"name": d.get("name", ""),
            "colors": "".join(c for c in "WUBRG" if c in d.get("color_identity", [])),
            "type": d.get("type_line") or face.get("type_line", ""),
            "url": d.get("scryfall_uri", "").split("?")[0],
            "img": imgs.get("normal", ""), "art": imgs.get("art_crop", ""),
            "cmc": d.get("cmc", face.get("cmc", 0)) or 0,
            "mana": d.get("mana_cost") or face.get("mana_cost", ""),
            "oracle": oracle[:600],
            "produces": "".join(c for c in "WUBRG" if c in (d.get("produced_mana") or [])),
            "kw": [k.lower() for k in (d.get("keywords") or [])],
            "rarity": d.get("rarity", "")}
    info["roles"] = card_roles(info)
    return info


# ------------------------------------------------------------------ card names
def find_arena_card_db():
    """Arena ships a SQLite card database; it has names for every card, digital-only ones included."""
    roots = [os.environ.get("ARENA_INSTALL_DIR", "")]
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        roots += [os.path.join(base, "Wizards of the Coast", "MTGA"),
                  os.path.join(base, "Steam", "steamapps", "common", "MTGA"),
                  os.path.join(base, "Epic Games", "MagicTheGathering")]
    for drive in "CDEFG":
        roots += [f"{drive}:\\SteamLibrary\\steamapps\\common\\MTGA",
                  f"{drive}:\\Steam\\steamapps\\common\\MTGA",
                  f"{drive}:\\Program Files\\Steam\\steamapps\\common\\MTGA"]
    found = []
    for r in filter(None, roots):
        found += glob.glob(os.path.join(r, "MTGA_Data", "Downloads", "Raw", "Raw_CardDatabase_*.mtga"))
    return max(found, key=os.path.getmtime) if found else None


def load_local_names():
    path = find_arena_card_db()
    if not path:
        return {}
    names = {}
    try:
        con = sqlite3.connect(f"file:{urllib.request.pathname2url(path)}?mode=ro", uri=True)
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "Localizations_enUS" in tables:
            q = ("select c.GrpId, l.Loc from Cards c join Localizations_enUS l "
                 "on l.LocId = c.TitleId and l.Formatted = 1")
        else:
            q = "select c.GrpId, l.enUS from Cards c join Localizations l on l.LocId = c.TitleId"
        for grp, name in con.execute(q):
            names.setdefault(str(grp), name)
        con.close()
    except Exception as e:
        log(f"Couldn't read Arena's card database ({e!r}); using Scryfall only.")
    return names


def load_local_abilities():
    path = find_arena_card_db()
    if not path:
        return {}
    out = {}
    try:
        con = sqlite3.connect(f"file:{urllib.request.pathname2url(path)}?mode=ro", uri=True)
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "Abilities" in tables:
            cols = {r[1] for r in con.execute("pragma table_info(Abilities)")}
            text_col = "TextId" if "TextId" in cols else None
            if text_col and "Localizations_enUS" in tables:
                q = ("select a.Id, l.Loc from Abilities a join Localizations_enUS l "
                     "on l.LocId = a.TextId and l.Formatted = 1")
            elif text_col:
                q = "select a.Id, l.enUS from Abilities a join Localizations l on l.LocId = a.TextId"
            else:
                q = None
            if q:
                for aid, txt in con.execute(q):
                    out.setdefault(str(aid), re.sub(r"<[^>]+>", "", txt or ""))
        con.close()
    except Exception as e:
        log(f"Couldn't read ability text ({e!r}).")
    return out


class Cards:
    """Arena card IDs -> names/colours/types via Scryfall, cached on disk."""

    def __init__(self):
        self.cache = load_json(CACHE_FILE, {})
        self.dirty = False
        self.failed = set()
        self._local = None

    def local_name(self, key):
        if self._local is None:
            self._local = load_local_names()
        return self._local.get(key)

    def get(self, grp_id):
        key = str(grp_id)
        if key in self.cache and "kw" in self.cache[key]:
            return self.cache[key]
        info = self.cache.get(key) or {"name": f"Card #{grp_id}", "colors": "", "type": "", "url": ""}
        if key in self.failed:
            return info
        try:
            req = urllib.request.Request(
                f"https://api.scryfall.com/cards/arena/{grp_id}",
                headers={"User-Agent": "ArenaTracker/2.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.load(r)
            info = scry_info(d)
            self.cache[key] = info
            self.dirty = True
            time.sleep(0.1)  # Scryfall asks for <= 10 requests/second
        except urllib.error.HTTPError as e:
            if e.code == 404:  # digital-only / brand new: name it from Arena's own database
                self.failed.add(key)
                name = self.local_name(key)
                if name:
                    info = {"name": name, "colors": "", "type": "", "url": "", "img": "", "art": "",
                            "cmc": 0, "mana": "", "oracle": "", "produces": "", "roles": [], "kw": []}
                    try:  # Scryfall often has the card by name even without an Arena ID
                        req = urllib.request.Request(
                            "https://api.scryfall.com/cards/named?exact=" + urllib.parse.quote(name),
                            headers={"User-Agent": "ArenaTracker/2.0", "Accept": "application/json"})
                        with urllib.request.urlopen(req, timeout=10) as r:
                            d = json.load(r)
                        info = scry_info(d)
                        time.sleep(0.1)
                    except Exception:
                        pass
                    self.cache[key] = info
                    self.dirty = True
        except Exception:
            pass  # offline: keep placeholder, retry next time
        return info

    def ability_text(self, aid):
        if not hasattr(self, "_abil"):
            self._abil = load_local_abilities()
        return self._abil.get(str(aid), "")

    def ensure_rarity(self, ids, limit=150):
        """Backfill rarity (for the wildcard planner) on cards cached before it was recorded."""
        n = 0
        for g in ids:
            key = str(g)
            c = self.cache.get(key)
            if not c or c.get("rarity") or key in self.failed or n >= limit:
                continue
            n += 1
            try:
                url = (f"https://api.scryfall.com/cards/arena/{g}" if c.get("url")
                       else "https://api.scryfall.com/cards/named?exact=" + urllib.parse.quote(c["name"]))
                req = urllib.request.Request(url, headers={"User-Agent": "ArenaTracker/2.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    c["rarity"] = json.load(r).get("rarity", "") or "unknown"
                self.dirty = True
                time.sleep(0.1)
            except Exception:
                c["rarity"] = c.get("rarity") or ""
                self.failed.add(key)

    def by_name(self, name):
        """Look a card up by name (for cards you don't own yet, e.g. the upgrade plan)."""
        key = "n:" + name.lower()
        if key in self.cache and self.cache[key].get("arena_rarity"):
            return self.cache[key]
        info = {"name": name, "img": "", "art": "", "url": "", "type": ""}
        try:
            req = urllib.request.Request(
                "https://api.scryfall.com/cards/named?exact=" + urllib.parse.quote(name),
                headers={"User-Agent": "ArenaTracker/2.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.load(r)
                info = scry_info(d)
            info["brawl"] = (d.get("legalities") or {}).get("brawl", "")
            try:  # the rarity that matters is the cheapest Arena printing
                q = urllib.parse.quote(f'!"{name}" game:arena')
                req = urllib.request.Request("https://api.scryfall.com/cards/search?unique=prints&q=" + q,
                                             headers={"User-Agent": "ArenaTracker/2.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    prints = json.load(r).get("data", [])
                rs = [p.get("rarity") for p in prints if p.get("rarity") in RARITY_COST]
                info["arena_rarity"] = min(rs, key=RARITY_COST.get) if rs else "not on Arena"  # crafting costs the cheapest Arena printing
            except urllib.error.HTTPError:
                info["arena_rarity"] = "not on Arena"
            except Exception:
                pass
            self.cache[key] = info
            self.dirty = True
            time.sleep(0.1)
        except Exception:
            pass
        return info

    def save(self):
        if self.dirty:
            save_json(CACHE_FILE, self.cache)
            self.dirty = False


# ------------------------------------------------------------------ parsing
class MatchParser:
    """Feed it log lines; it builds one detailed record per match."""

    def __init__(self, store, config):
        self.store = store
        self.config = config
        self.cur = None
        self.new_match = False
        self.deck_meta = {}
        self.last_finished = None
        self.want_rank = False
        self.live = False
        self.last_ts = 0
        self.wildcards = load_json(WILDCARDS_FILE, [])
        self.pending_inv = None
        self.decks = load_json(DECKS_FILE, [])

    def feed(self, line):
        if "matchGameRoomStateChangedEvent" in line:
            self._room_event(line)
        elif self.cur is not None and "greToClientEvent" in line:
            self._gre_event(line)
        elif "==> EventSetDeck" in line or "==> DeckUpsertDeck" in line:
            self._deck_event(line)
        elif '"WildCardCommons"' in line:
            self._inventory(line)
        elif "<== RankGetCombinedRankInfo" in line:
            self.want_rank = True
        elif self.want_rank and line.startswith("{"):
            self.want_rank = False
            self._rank_event(line)

    def _deck_event(self, line):
        try:
            req = json.loads(json.loads(line[line.index("{"):])["request"])
            summ = req.get("Summary", {})
            attrs = {a.get("name"): a.get("value") for a in summ.get("Attributes", [])}
            cards = []
            for c in (req.get("Deck") or {}).get("MainDeck", []):
                cards += [c["cardId"]] * int(c.get("quantity", 1))
            self.deck_meta = {"name": summ.get("Name", ""), "id": summ.get("DeckId", ""),
                              "ver": attrs.get("Version", ""), "cards": sorted(cards)}
            cmds = [c["cardId"] for c in (req.get("Deck") or {}).get("CommandZone", [])]
            self._record_deck(self.deck_meta, cmds, (attrs.get("LastUpdated") or "").strip('"'))
        except (ValueError, KeyError, TypeError):
            pass

    def _inventory(self, line):
        def num(k):
            m = re.search(r'"%s":\s*(\d+)' % k, line)
            return int(m.group(1)) if m else 0
        snap = {"c": num("WildCardCommons"), "u": num("WildCardUnCommons"), "r": num("WildCardRares"),
                "m": num("WildCardMythics"), "gold": num("Gold"), "gems": num("Gems")}
        if not re.search(r'"Gems":\s*\d', line):  # partial update, not a full inventory
            return
        if self.live:
            self.record_inventory(snap, int(time.time() * 1000))
        else:
            self.pending_inv = snap  # during the initial import keep only the latest

    def record_inventory(self, snap, ts):
        last = self.wildcards[-1] if self.wildcards else None
        if last and all(last.get(k) == v for k, v in snap.items()):
            return
        self.wildcards.append(dict(snap, ts=ts))
        save_json(WILDCARDS_FILE, self.wildcards)
        self.new_match = True  # rebuild the dashboard

    def _record_deck(self, meta, commanders, saved):
        """Keep every distinct version of every deck you save or queue with."""
        if not meta.get("cards"):
            return
        if any(d["id"] == meta["id"] and d["cards"] == meta["cards"] for d in self.decks):
            return
        self.decks.append({"id": meta["id"], "name": meta["name"], "saved": saved[:19],
                           "cards": meta["cards"], "commanders": commanders,
                           "seen": int(time.time() * 1000) if self.live else self.last_ts})
        save_json(DECKS_FILE, self.decks)
        self.new_match = True

    def _rank_event(self, line):
        try:
            r = json.loads(line)
        except ValueError:
            return
        rank = {"class": r.get("constructedClass"), "level": r.get("constructedLevel"),
                "step": r.get("constructedStep"), "won": r.get("constructedMatchesWon"),
                "lost": r.get("constructedMatchesLost")}
        if not rank["class"]:
            return
        self.config["last_rank"] = rank
        m = self.store.get(self.last_finished) if self.last_finished else None
        if m is not None and "rank_after" not in m:
            m["rank_after"] = rank
            self.new_match = True

    # --- match start / end
    def _room_event(self, line):
        try:
            d = json.loads(line[line.index("{"):])
        except ValueError:
            return
        info = d.get("matchGameRoomStateChangedEvent", {}).get("gameRoomInfo", {})
        cfg = info.get("gameRoomConfig", {})
        match_id = cfg.get("matchId")
        if not match_id:
            return
        state = info.get("stateType", "")
        players = cfg.get("reservedPlayers", [])
        ts = int(d.get("timestamp", 0) or 0)

        if state == "MatchGameRoomStateType_Playing":
            if self.cur is None or self.cur["match_id"] != match_id:
                self.cur = {
                    "match_id": match_id, "start": ts,
                    "event": players[0].get("eventId", "") if players else "",
                    "players": {str(p["systemSeatId"]): {
                        "name": p.get("playerName", ""), "user_id": p.get("userId", ""),
                        "team": p.get("teamId", p["systemSeatId"])} for p in players},
                    "my_seat": None,
                    "commanders": defaultdict(set), "seen": defaultdict(set),
                    "objs": {}, "zones": {}, "turn": 0, "active": None,
                    "life": {}, "life_lost": Counter(), "life_gained": Counter(),
                    "plays": [], "play_keys": set(), "snaps": {}, "active_by_turn": {},
                    "mull_reqs": Counter(), "hands": [], "draws": [], "removals": [],
                    "dmg_log": [], "board": {}, "deck": None, "id_map": {},
                    "last_hit": {}, "deck_meta": dict(self.deck_meta),
                    "rank_before": self.config.get("last_rank"),
                    "turn_start": {}, "combat": {}, "hand_by_turn": {}, "precombat": {}, "phase": "",
                    "abil": {}, "countered": [], "events": [], "ev_keys": set(),
                    "reveals": [], "rev_keys": set(),
                }
        elif state == "MatchGameRoomStateType_MatchCompleted":
            if self.cur is None or self.cur["match_id"] != match_id:
                return
            winner, reason = None, ""
            for r in info.get("finalMatchResult", {}).get("resultList", []):
                if r.get("scope") == "MatchScope_Match":
                    winner = r.get("winningTeamId")
                    reason = r.get("reason", "").replace("ResultReason_", "")
            self._finish(winner, reason, ts)

    # --- game state updates
    def _gre_event(self, line):
        try:
            d = json.loads(line[line.index("{"):])
        except ValueError:
            return
        if False:   # (debug capture of reveal messages, off)
            try:
                if not os.path.exists(RAW_REVEALS) or os.path.getsize(RAW_REVEALS) < RAW_REVEALS_MAX:
                    with open(RAW_REVEALS, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"match": (self.cur or {}).get("match_id"), "my_seat": (self.cur or {}).get("my_seat"),
                                            "msg": d}) + "\n")
            except OSError:
                pass
        cur = self.cur
        ts = int(d.get("timestamp", 0) or 0)
        if ts:
            self.last_ts = ts
        for msg in d.get("greToClientEvent", {}).get("greToClientMessages", []):
            seats = msg.get("systemSeatIds") or []
            if len(seats) == 1 and cur["my_seat"] is None:
                cur["my_seat"] = str(seats[0])
            if msg.get("type") == "GREMessageType_MulliganReq" and seats:
                seat = str(seats[0])
                cur["mull_reqs"][seat] += 1
                hand = next((z["ids"] for z in cur["zones"].values()
                             if z["type"] == "ZoneType_Hand" and str(z["owner"]) == seat), [])
                cur["hands"].append([cur["objs"][i]["grpId"] for i in hand
                                     if i in cur["objs"] and cur["objs"][i].get("grpId")])
            if msg.get("type") == "GREMessageType_GroupReq" and seats:
                gq = msg.get("groupReq") or {}
                if gq.get("context") == "GroupingContext_LondonMulligan":
                    n = next((gsp.get("lowerBound") for gsp in gq.get("groupSpecs", [])
                              if gsp.get("zoneType") == "ZoneType_Library"), 0)
                    cur["bottom_req"] = {"seat": str(seats[0]), "n": n or 0}
            if msg.get("type") == "GREMessageType_ConnectResp":
                dm = msg.get("connectResp", {}).get("deckMessage", {})
                if dm.get("deckCards"):
                    cur["deck"] = {"cards": sorted(dm.get("deckCards", [])),
                                   "commanders": sorted(dm.get("commanderCards", []))}
            gs = msg.get("gameStateMessage")
            if gs:
                self._apply_state(gs, ts)

    def _apply_state(self, gs, ts=0):
        cur = self.cur
        objs, zones = cur["objs"], cur["zones"]

        for z in gs.get("zones", []):
            zones[z.get("zoneId")] = {"type": z.get("type", ""), "owner": z.get("ownerSeatId"),
                                      "ids": z.get("objectInstanceIds", [])}
        for o in gs.get("gameObjects", []):
            objs[o.get("instanceId")] = o
            if o.get("type") == "GameObjectType_RevealedCard" and o.get("grpId"):
                self._note_known(o)
            if o.get("type") != "GameObjectType_Card" or not o.get("grpId"):
                continue
            owner = str(o.get("ownerSeatId"))
            ctypes = o.get("cardTypes", [])
            if (zones.get(o.get("zoneId"), {}).get("type") == "ZoneType_Command"
                    and any(t in ctypes for t in ("CardType_Creature", "CardType_Planeswalker", "CardType_Artifact"))
                    and "CardType_Dungeon" not in ctypes):
                cur["commanders"][owner].add(o["grpId"])
            if o.get("visibility") == "Visibility_Public":
                cur["seen"][owner].add(o["grpId"])

        ti = gs.get("turnInfo", {})
        if ti.get("turnNumber"):
            cur["turn"] = max(cur["turn"], ti["turnNumber"])
            if ts and cur["turn"] not in cur["turn_start"]:
                cur["turn_start"][cur["turn"]] = ts

        # combat: attackers and blockers as they're declared
        if cur["turn"]:
            cb = cur["combat"].setdefault(cur["turn"], {"att": {}, "blk": {}})
            for o in gs.get("gameObjects", []):
                st = o.get("attackState")
                if st in ("AttackState_Attacking", "AttackState_Declared") and o.get("grpId"):
                    tgt = (o.get("attackInfo") or {}).get("targetId")
                    cb["att"][o["instanceId"]] = [o["grpId"], (o.get("power") or {}).get("value"),
                                                  str(o.get("controllerSeatId")), tgt]
                bi = o.get("blockInfo") or {}
                if o.get("blockState") in ("BlockState_Blocking", "BlockState_Declared") and bi.get("attackerIds") and o.get("grpId"):
                    cb["blk"][o["instanceId"]] = [o["grpId"], bi["attackerIds"]]
        if ti.get("activePlayer"):
            cur["active"] = str(ti["activePlayer"])
            if cur["turn"]:
                cur["active_by_turn"][cur["turn"]] = cur["active"]

        for p in gs.get("players", []):
            if "lifeTotal" not in p:
                continue
            seat = str(p.get("systemSeatNumber"))
            new = p["lifeTotal"]
            old = cur["life"].get(seat)
            if old is not None and new != old:
                if new < old:
                    cur["life_lost"][seat] += old - new
                else:
                    cur["life_gained"][seat] += new - old
            cur["life"][seat] = new

        seats = {int(x) for x in cur["players"]}
        for a in gs.get("annotations", []):
            types = a.get("type", [])
            det = {dd.get("key"): (dd.get("valueInt32") or dd.get("valueString") or [None])[0]
                   for dd in a.get("details", [])}
            if ("AnnotationType_CounterAdded" in types or "AnnotationType_CounterRemoved" in types) \
                    and det.get("counter_type") == 3:   # 3 = poison counters on a player
                for tgt in a.get("affectedIds", []):
                    if tgt in seats:
                        sign = 1 if "AnnotationType_CounterAdded" in types else -1
                        pz = cur.setdefault("poison", {})
                        pz[str(tgt)] = max(0, pz.get(str(tgt), 0) + sign * int(det.get("transaction_amount") or 1))
            if "AnnotationType_ObjectIdChanged" in types:
                if det.get("orig_id") and det.get("new_id"):
                    cur["id_map"][det["new_id"]] = det["orig_id"]
                continue
            if "AnnotationType_DamageDealt" in types:
                src = self._source(a.get("affectorId"))
                amt = det.get("damage") or 0
                for tgt in a.get("affectedIds", []):
                    if tgt in seats:
                        target = str(tgt)
                    else:
                        target = "creature"
                        if src:
                            cur["last_hit"][tgt] = src
                    if src and amt:
                        cur["dmg_log"].append([cur["turn"], src[0], src[1], target, amt, det.get("type") == 1])
                continue
            if "AnnotationType_TargetSpec" in types or "AnnotationType_AttachmentCreated" in types:
                kind = "attach" if "AnnotationType_AttachmentCreated" in types else "target"
                src = objs.get(a.get("affectorId")) or {}
                sg = src.get("grpId") if src.get("type") != "GameObjectType_Ability" else src.get("objectSourceGrpId")
                sseat = str(src.get("controllerSeatId") or src.get("ownerSeatId") or "")
                for tid in a.get("affectedIds", []):
                    o = objs.get(tid)
                    key = (a.get("affectorId"), tid, kind)
                    if not sg or not o or not o.get("grpId") or key in cur["ev_keys"]:
                        continue
                    cur["ev_keys"].add(key)
                    cur["events"].append({"ms": ts, "t": cur["turn"], "kind": kind, "src": sg, "seat": sseat,
                                          "tgt": o["grpId"],
                                          "tseat": str(o.get("controllerSeatId") or o.get("ownerSeatId") or "")})
                continue
            if "AnnotationType_ZoneTransfer" not in types:
                continue
            cat = det.get("category") or ""
            src_zone = cur["zones"].get(det.get("zone_src"), {}).get("type")
            if cat == "Draw":
                for iid in a.get("affectedIds", []):
                    o = objs.get(iid)
                    if o and o.get("grpId") and str(o.get("ownerSeatId")) == cur["my_seat"]:
                        cur["draws"].append([cur["turn"], o["grpId"]])
                continue
            if src_zone == "ZoneType_Battlefield" and cat in REMOVAL:
                for iid in a.get("affectedIds", []):
                    o = objs.get(iid)
                    if not o or not o.get("grpId"):
                        continue
                    killer = self._source(a.get("affectorId"))
                    if not killer:  # died to damage: credit whatever last hit it
                        old = cur["id_map"].get(iid, iid)
                        killer = cur["last_hit"].get(old) or cur["last_hit"].get(iid)
                    cur["removals"].append({
                        "ms": ts, "t": cur["turn"], "seat": str(o.get("ownerSeatId")), "g": o["grpId"],
                        "creature": "CardType_Creature" in o.get("cardTypes", []),
                        "how": cat, "by_seat": killer[0] if killer else None,
                        "by": killer[1] if killer else None})
                continue
            if cat not in ("CastSpell", "PlayLand"):
                continue
            for iid in a.get("affectedIds", []):
                o = objs.get(iid)
                if not o or not o.get("grpId") or (iid, cat) in cur["play_keys"]:
                    continue
                cur["play_keys"].add((iid, cat))
                cur["plays"].append({"ms": ts, "t": cur["turn"], "s": str(o.get("controllerSeatId") or o.get("ownerSeatId")),
                                     "g": o["grpId"], "k": "land" if cat == "PlayLand" else "spell",
                                     "ph": (gs.get("turnInfo") or {}).get("phase") or cur.get("phase")})

        my_cmds = cur["commanders"].get(cur["my_seat"] or "", set())
        for o in gs.get("gameObjects", []):
            if (o.get("type") == "GameObjectType_Ability" and o.get("objectSourceGrpId") in my_cmds
                    and str(o.get("controllerSeatId")) == cur["my_seat"] and o["instanceId"] not in cur["abil"]):
                cur["abil"][o["instanceId"]] = {"t": cur["turn"], "ab": o.get("grpId"), "src": o["objectSourceGrpId"],
                                                "added": 0, "targets": []}
        for a in gs.get("annotations", []):
            types = a.get("type", [])
            if "AnnotationType_CounterAdded" in types and a.get("affectorId") in cur["abil"]:
                amt = 0
                for dd in a.get("details", []):
                    if dd.get("key") in ("transaction_amount", "amount"):
                        amt = (dd.get("valueInt32") or [0])[0]
                rec = cur["abil"][a["affectorId"]]
                rec["added"] += amt or 0
                for iid in a.get("affectedIds", []):
                    o = objs.get(iid)
                    if o and o.get("grpId"):
                        rec["targets"].append(o["grpId"])
            if "AnnotationType_ZoneTransfer" in types:
                cat = next((dd.get("valueString", [""])[0] for dd in a.get("details", []) if dd.get("key") == "category"), "")
                if cat == "Countered":
                    by = self._source(a.get("affectorId"))
                    for iid in a.get("affectedIds", []):
                        o = objs.get(iid)
                        if o and o.get("grpId"):
                            cur["countered"].append({"ms": ts, "t": cur["turn"], "g": o["grpId"],
                                                     "seat": str(o.get("ownerSeatId")),
                                                     "by": by[1] if by else None, "by_seat": by[0] if by else None})

        for iid in gs.get("diffDeletedInstanceIds", []):
            objs.pop(iid, None)

        if ti.get("phase"):
            cur["phase"] = ti["phase"]
        if cur["turn"]:
            self._snapshot()
            # board as you went to combat (or skipped it), on your own turns
            if (cur["active"] and cur["active"] == cur["my_seat"] and cur["turn"] not in cur["precombat"]
                    and cur["phase"] in ("Phase_Combat", "Phase_Main2", "Phase_Ending")):
                cur["precombat"][cur["turn"]] = {"board": json.loads(json.dumps(cur["board"][cur["turn"]])),
                                                 "life": dict(cur["life"])}

    def _note_known(self, o):
        """Arena shows a revealed card as a 'RevealedCard' copy that points at the zone the real card sits in
        (their hand, a library...). Log each one for the game record; what's known *now* is read off the zones."""
        cur = self.cur
        key = o.get("instanceId")
        if key in cur["rev_keys"]:
            return
        cur["rev_keys"].add(key)
        where = (cur["zones"].get(o.get("zoneId")) or {}).get("type", "").replace("ZoneType_", "")
        cur["reveals"].append({"t": cur["turn"], "seat": str(o.get("ownerSeatId")), "g": o["grpId"], "zone": where})

    def _source(self, iid):
        """(seat, grpId) of whatever card an instance (card or ability) came from."""
        o = self.cur["objs"].get(iid)
        if not o:
            return None
        grp = o.get("objectSourceGrpId") if o.get("type") == "GameObjectType_Ability" else o.get("grpId")
        if not grp:
            return None
        return (str(o.get("controllerSeatId") or o.get("ownerSeatId")), grp)

    def _snapshot(self):
        """Board state for every seat, overwritten until the turn ends."""
        cur = self.cur
        battlefield = set()
        hands = Counter()
        gy, ex = defaultdict(list), defaultdict(list)
        for z in cur["zones"].values():
            if z["type"] == "ZoneType_Battlefield":
                battlefield.update(z["ids"])
            elif z["type"] == "ZoneType_Hand":
                hands[str(z["owner"])] = len(z["ids"])
            elif z["type"] in ("ZoneType_Graveyard", "ZoneType_Exile"):
                for iid in z["ids"]:
                    o = cur["objs"].get(iid) or {}
                    who = str(o.get("ownerSeatId") or z.get("owner") or "")
                    if z["type"] == "ZoneType_Graveyard":
                        if o.get("grpId"):
                            gy[who].append(o["grpId"])
                    elif o.get("type") in (None, "GameObjectType_Card"):
                        ex[who].append(o.get("grpId") or 0)   # 0 = face down
        snap = {}
        for seat in cur["players"]:
            snap[seat] = {"life": cur["life"].get(seat), "creatures": 0, "power": 0,
                          "biggest": 0, "lands": 0, "permanents": 0, "hand": hands.get(seat, 0),
                          "poison": (cur.get("poison") or {}).get(str(seat), 0),
                          "gy": gy.get(str(seat), []), "ex": ex.get(str(seat), [])}
        board = {seat: [] for seat in cur["players"]}
        for iid in battlefield:
            o = cur["objs"].get(iid)
            if not o:
                continue
            seat = str(o.get("controllerSeatId", o.get("ownerSeatId")))
            s = snap.get(seat)
            if s is None:
                continue
            types = o.get("cardTypes", [])
            if o.get("grpId") and o.get("type") in ("GameObjectType_Card", "GameObjectType_Token"):
                is_cre = "CardType_Creature" in types
                board[seat].append([o["grpId"],
                                    (o.get("power") or {}).get("value") if is_cre else None,
                                    (o.get("toughness") or {}).get("value") if is_cre else None,
                                    1 if o.get("isTapped") else 0,
                                    1 if "CardType_Land" in types else 0,
                                    1 if o.get("type") == "GameObjectType_Token" else 0,
                                    1 if o.get("hasSummoningSickness") else 0])
            s["permanents"] += 1
            if "CardType_Land" in types:
                s["lands"] += 1
            if "CardType_Creature" in types:
                p = (o.get("power") or {}).get("value", 0) or 0
                s["creatures"] += 1
                s["power"] += max(p, 0)
                s["biggest"] = max(s["biggest"], p)
        cur["snaps"][cur["turn"]] = snap
        cur["board"][cur["turn"]] = board
        if cur["my_seat"]:
            hand = next((z["ids"] for z in cur["zones"].values()
                         if z["type"] == "ZoneType_Hand" and str(z["owner"]) == cur["my_seat"]), [])
            cur["hand_by_turn"][cur["turn"]] = [cur["objs"][i]["grpId"] for i in hand
                                                if i in cur["objs"] and cur["objs"][i].get("grpId")]

    def _finish(self, winner, reason, ts):
        cur = self.cur
        self.cur = None
        players = cur["players"]
        my_id = self.config.get("my_user_id")
        my_seat = next((s for s, p in players.items() if my_id and p["user_id"] == my_id), None)
        if my_seat is None:
            my_seat = cur["my_seat"]
        if my_seat not in players:
            return
        opp_seat = next((s for s in players if s != my_seat), None)
        if opp_seat is None:
            return
        side = {my_seat: "me", opp_seat: "opp"}
        my_team = players[my_seat]["team"]
        result = "Draw" if winner is None else ("Win" if winner == my_team else "Loss")

        timeline = []
        for t in sorted(cur["snaps"]):
            snap = cur["snaps"][t]
            timeline.append({"t": t, "a": side.get(cur["active_by_turn"].get(t), ""),
                             "me": snap.get(my_seat), "opp": snap.get(opp_seat)})
        plays = [dict({"t": p["t"], "side": side.get(p["s"], "?"), "g": p["g"], "k": p["k"], "ms": p.get("ms")},
                      **({"ph": p["ph"].replace("Phase_", "")} if p.get("ph") else {}))
                 for p in cur["plays"]]
        first = next((side.get(cur["active_by_turn"][t]) for t in sorted(cur["active_by_turn"])), None)

        # damage, aggregated by source card
        dmg = {"me": {"to_player": Counter(), "to_creature": Counter(), "combat": 0, "noncombat": 0},
               "opp": {"to_player": Counter(), "to_creature": Counter(), "combat": 0, "noncombat": 0}}
        for t, src_seat, grp, target, amt, combat in cur["dmg_log"]:
            sd = side.get(src_seat)
            if sd is None:
                continue
            d = dmg[sd]
            if target == "creature":
                d["to_creature"][str(grp)] += amt
            elif target != src_seat:
                d["to_player"][str(grp)] += amt
                d["combat" if combat else "noncombat"] += amt
        for sd in dmg.values():
            sd["to_player"] = dict(sd["to_player"])
            sd["to_creature"] = dict(sd["to_creature"])

        removals = [{"ms": r.get("ms"), "t": r["t"], "side": side.get(r["seat"], "?"), "g": r["g"], "creature": r["creature"],
                     "how": REMOVAL.get(r["how"], r["how"]),
                     "by_side": side.get(r["by_seat"]), "by": r["by"]} for r in cur["removals"]]

        my_cmds = set(cur["commanders"].get(my_seat, []))
        opp_cmds = set(cur["commanders"].get(opp_seat, []))
        cmd = {"me": {"casts": [p["t"] for p in plays if p["side"] == "me" and p["g"] in my_cmds],
                      "deaths": sum(1 for r in removals if r["side"] == "me" and r["g"] in my_cmds)},
               "opp": {"casts": [p["t"] for p in plays if p["side"] == "opp" and p["g"] in opp_cmds],
                       "deaths": sum(1 for r in removals if r["side"] == "opp" and r["g"] in opp_cmds)}}

        hands = [h for h in cur["hands"] if h]
        kept = hands[-1] if hands else []
        deck = cur["deck"] or {}
        deck_info = dict(cur["deck_meta"])
        deck_cards = deck.get("cards") or deck_info.get("cards", [])
        if deck_cards:
            deck_info["cards"] = deck_cards
            deck_info["hash"] = format(sum((i + 1) * g for i, g in enumerate(deck_cards)) % (16 ** 8), "08x")

        combat = {}
        for t, cb in cur["combat"].items():
            if not cb["att"]:
                continue
            att_grp = {iid: a[0] for iid, a in cb["att"].items()}
            combat[str(t)] = {
                "att": [[a[0], a[1], side.get(a[2], "?"),
                         "player" if a[3] in (1, 2) else "planeswalker/battle"] for a in cb["att"].values()],
                "blk": [[b[0], [att_grp.get(x) for x in b[1] if x in att_grp]] for b in cb["blk"].values()],
            }
        starts = sorted(cur["turn_start"].items())
        turn_secs = {}
        for i, (t, t0) in enumerate(starts):
            t1 = starts[i + 1][1] if i + 1 < len(starts) else ts
            if t1 and t1 >= t0:
                turn_secs[str(t)] = round((t1 - t0) / 1000)

        precombat = {}
        for t, pc in cur["precombat"].items():
            precombat[str(t)] = {"me": pc["board"].get(my_seat, []), "opp": pc["board"].get(opp_seat, []),
                                 "my_life": pc["life"].get(my_seat), "opp_life": pc["life"].get(opp_seat)}

        board = {}
        for t in sorted(cur["board"]):
            b = cur["board"][t]
            board[str(t)] = {"me": b.get(my_seat, []), "opp": b.get(opp_seat, []),
                             "hand": cur["hand_by_turn"].get(t, []) if my_seat == cur["my_seat"] else []}

        tracked = self.config.get("track_events") or TRACKED_EVENTS
        limited = is_limited_event(cur.get("event"))
        if limited or (tracked and cur.get("event") not in tracked):
            log(f"Skipped a {EVENT_NAMES.get(cur.get('event'), cur.get('event'))} game.")
            return
        target = {} if limited else self.store
        target[cur["match_id"]] = {
            "v": VERSION, "match_id": cur["match_id"], "start": cur["start"], "end": ts,
            "event": cur["event"], "result": result, "reason": reason, "turns": cur["turn"],
            "on_play": first == "me",
            "my_name": players[my_seat]["name"], "my_user_id": players[my_seat]["user_id"],
            "opp_name": players[opp_seat]["name"],
            "my_commanders": sorted(cur["commanders"].get(my_seat, [])),
            "opp_commanders": sorted(cur["commanders"].get(opp_seat, [])),
            "opp_seen": sorted(cur["seen"].get(opp_seat, [])),
            "my_life": cur["life"].get(my_seat), "opp_life": cur["life"].get(opp_seat),
            "life_lost": {"me": cur["life_lost"][my_seat], "opp": cur["life_lost"][opp_seat]},
            "life_gained": {"me": cur["life_gained"][my_seat], "opp": cur["life_gained"][opp_seat]},
            "mulligans": max(0, len([h for h in cur["hands"] if h]) - 1) if cur["hands"]
                         else max(0, cur["mull_reqs"][my_seat] - 1),
            "timeline": timeline, "plays": plays,
            "hands": hands, "kept": kept, "draws": cur["draws"], "removals": removals,
            "damage": dmg, "cmd": cmd, "board": board, "deck": deck_info,
            "rank_before": cur["rank_before"],
            "combat": combat, "turn_secs": turn_secs, "precombat": precombat,
            "turn_ts": {str(t): t0 for t, t0 in starts},
            "cmd_uses": [dict(v) for v in cur["abil"].values()],
            "events": [{"ms": e["ms"], "t": e["t"], "kind": e["kind"], "src": e["src"], "by": side.get(e["seat"], "?"),
                        "tgt": e["tgt"], "tside": side.get(e["tseat"], "?")} for e in cur["events"]],
            "countered": [{"ms": c.get("ms"), "t": c["t"], "g": c["g"], "side": side.get(c["seat"], "?"), "by": c["by"],
                           "by_side": side.get(c["by_seat"])} for c in cur["countered"]],
            "reveals": [{"t": r["t"], "side": side.get(r["seat"], "?"), "g": r["g"], "zone": r.get("zone")}
                        for r in cur["reveals"]],
        }
        if limited:   # draft / sealed: saved for the draft net, kept out of your Brawl history
            if self.live:
                lg = load_json(LIMITED_FILE, {})
                lg.update(target)
                save_json(LIMITED_FILE, lg)
                rec = target[cur["match_id"]]
                log(f"Draft game saved: {rec['result']} vs {rec['opp_name']} ({rec['turns']} turns). "
                    f"{len(lg)} Limited games recorded.")
            return
        self.last_finished = cur["match_id"]
        self.new_match = True


def learn_my_user_id(store, config):
    """The account present in the most matches is the tracker's owner."""
    counts = Counter(m["my_user_id"] for m in store.values() if m.get("my_user_id"))
    if counts and not config.get("my_user_id"):
        config["my_user_id"] = counts.most_common(1)[0][0]
        save_json(CONFIG_FILE, config)


# ------------------------------------------------------------------ outputs
DEFAULT_UPGRADES = {
    "note": "Your upgrade plan: cards you want to add, in stages. A card is ticked off once it's in your latest deck.",
    "stages": [],
}

CREATURE_ANSWER = re.compile(r"(destroy|exile) target (nonland )?(creature|permanent)|return target (nonland )?(creature|permanent)"
                             r"|target creature .{0,40}becomes|deals damage equal to its power to (target|another target)"
                             r"|destroy target (artifact or )?creature|loses all abilities|target creature an opponent controls"
                             r"|return all|destroy all|exile all")
SPELL_ANSWER = re.compile(r"counter target")
NONCRE_ANSWER = re.compile(r"(destroy|exile) target (nonland )?(permanent|artifact|enchantment|planeswalker)"
                           r"|return target nonland permanent|return all nonland|destroy target artifact, enchantment"
                           r"|(artifact|enchantment|planeswalker) or")


def answers_for(threat, deck_ids, cards):
    """Cards in your deck that could deal with a given opposing card."""
    t = cards.get(threat).get("type", "")
    res = []
    for g in dict.fromkeys(deck_ids):
        c = cards.get(g)
        o = (c.get("oracle") or "").lower()
        if not o or "Land" in c.get("type", "") and "Creature" not in c.get("type", ""):
            continue
        if SPELL_ANSWER.search(o) and ("noncreature" not in o or "Creature" not in t):
            res.append(g)
        elif "Creature" in t and CREATURE_ANSWER.search(o):
            res.append(g)
        elif "Creature" not in t and NONCRE_ANSWER.search(o):
            res.append(g)
    return res


def review_interaction(m, cards, deck_ids):
    """What you answered, what you let through, and what would have saved you."""
    out = {"used": [], "let_through": [], "saved_by": None}
    cmds = set(m.get("opp_commanders", []))
    for r in m.get("removals", []):
        if r.get("by_side") == "me" and r["side"] == "opp" and r.get("by"):
            out["used"].append({"t": r["t"], "by": r["by"], "g": r["g"], "how": r["how"], "commander": r["g"] in cmds})
    for c in m.get("countered", []):
        if c.get("by_side") == "me" and c["side"] == "opp":
            out["used"].append({"t": c["t"], "by": c["by"], "g": c["g"], "how": "Countered", "commander": c["g"] in cmds})

    # opposing cards that hurt you most, and whether you sat on an answer
    harm = Counter()
    for g, v in ((m.get("damage") or {}).get("opp") or {}).get("to_player", {}).items():
        harm[int(g)] += v
    for r in m.get("removals", []):
        if r["side"] == "me" and r.get("by_side") == "opp" and r.get("by"):
            harm[r["by"]] += 4
    cast_t = {}
    for p in m.get("plays", []):
        if p["side"] == "opp":
            cast_t.setdefault(p["g"], p["t"])
    board = m.get("board") or {}
    for g, score in harm.most_common(4):
        if score < 5:
            continue
        t0 = cast_t.get(g)
        held = set()
        if t0 is not None:
            for t in range(t0 - 1, (m.get("turns") or t0) + 1):
                b = board.get(str(t)) or {}
                lands = sum(1 for c in b.get("me", []) if c[4])
                has_creature = any(c[1] is not None for c in b.get("me", []))
                for h in b.get("hand", []):
                    c = cards.get(h)
                    o = (c.get("oracle") or "").lower()
                    if (c.get("cmc") or 0) > lands:
                        continue  # couldn't afford it yet
                    if ("its power" in o or "fights" in o) and not has_creature:
                        continue  # bite/fight needs a creature of yours
                    if h in answers_for(g, [h], cards):
                        held.add(h)
        out["let_through"].append({"g": g, "harm": round(score), "t": t0, "held": sorted(held)})

    if m.get("result") == "Loss" and harm:
        killer = harm.most_common(1)[0][0]
        ans = answers_for(killer, deck_ids, cards)
        held = next((x["held"] for x in out["let_through"] if x["g"] == killer), [])
        out["saved_by"] = {"g": killer, "harm": round(harm[killer]), "answers": ans[:8], "held": held}
    return out


def make_recap(m, cards):
    """A few lines for the overlay right after a game."""
    nm = lambda g: cards.get(g)["name"]
    lines = [f"{'WIN' if m['result'] == 'Win' else 'LOSS' if m['result'] == 'Loss' else m['result']} vs "
             + " + ".join(nm(g) for g in m.get("opp_commanders", [])) + f" · {m.get('turns')} turns"]
    ra, rb = m.get("rank_after"), m.get("rank_before")
    if ra and rb:
        lines.append(f"Rank: {rb.get('class')} {rb.get('level')} → {ra.get('class')} {ra.get('level')}")
    for x in (m.get("attack_review") or []):
        if x["kind"] in ("missed", "bad"):
            lines.append(f"T{x['t']}: {x['text'][:110]}")
            if len(lines) >= 4:
                break
    iv = m.get("interaction") or {}
    sb = iv.get("saved_by")
    if sb:
        if sb["held"]:
            lines.append(f"{nm(sb['g'])} beat you — you were holding {', '.join(nm(h) for h in sb['held'][:2])}.")
        elif sb["answers"]:
            lines.append(f"{nm(sb['g'])} beat you — answers in your deck: {', '.join(nm(h) for h in sb['answers'][:3])}.")
    uses = [u for u in m.get("cmd_uses", []) if u.get("kind") == "activated"]
    if m.get("cmd_uses") is not None:
        lines.append(f"Commander ability activated {len(uses)}×.")
    return lines[:6]


LAST_RECAP = {"ts": 0, "lines": []}

ADVISOR = {}   # read by the overlay: historical win rates for kept hands
SCOUT = {}     # read by the overlay: what each opponent commander has shown you


def hand_features(hand, cards):
    f = {"lands": 0, "ramp": 0, "interaction": 0, "draw": 0, "cheap": 0}
    for g in hand:
        c = cards.get(g)
        roles = c.get("roles") or card_roles(c)
        if "land" in roles:
            f["lands"] += 1
            continue
        for r in ("ramp", "interaction", "draw"):
            if r in roles:
                f[r] += 1
        if (c.get("cmc") or 99) <= 2:
            f["cheap"] += 1
    return f


NEUTER_RE = re.compile(r"enchant(ed)? creature[^.]*(loses all abilities|base power and toughness 1/1)")


def analyze_attacks(m, cards):
    """Heuristic review of each of your combats. Returns [{t, kind, text}]."""
    tl = m.get("timeline") or []
    board, combat, pre_all = m.get("board") or {}, m.get("combat") or {}, m.get("precombat") or {}
    if not tl or not board:
        return []
    by_t = {x["t"]: x for x in tl}
    kw = lambda g: set(cards.get(g).get("kw") or [])
    name = lambda g: cards.get(g)["name"]
    out = []
    opp_cmds = set(m.get("opp_commanders") or [])
    said_locked = []

    def can_block(b, a):
        ka, kb = kw(a[0]), kw(b[0])
        if "flying" in ka and not ({"flying", "reach"} & kb):
            return False
        if "unblockable" in ka or "shadow" in ka:
            return False
        return True

    def worst_case(attackers, blockers):
        """Damage that gets through if they block the biggest attackers they can."""
        free = list(blockers)
        dmg = 0
        for a in sorted(attackers, key=lambda c: -(c[1] or 0)):
            b = next((b for b in sorted(free, key=lambda c: -(c[2] or 0)) if can_block(b, a)), None)
            if b is None:
                dmg += a[1] or 0
            else:
                free.remove(b)
                if "trample" in kw(a[0]):
                    dmg += max(0, (a[1] or 0) - (b[2] or 0))
        return dmg

    for x in tl:
        if x.get("a") != "me":
            continue
        t = x["t"]
        prev, now, nxt = by_t.get(t - 1), x, by_t.get(t + 1)
        pre = pre_all.get(str(t))
        if pre:
            mine, theirs = pre["me"], pre["opp"]
            opp_life, my_life = pre.get("opp_life"), pre.get("my_life")
            exact = True
        else:  # older games: fall back to the board at the end of their previous turn
            pb = board.get(str(t - 1))
            if not pb or not prev:
                continue
            mine = [c[:3] + [0] + c[4:6] + [0] for c in pb["me"]]  # your creatures untap
            theirs = pb["opp"]
            opp_life, my_life = (prev.get("opp") or {}).get("life"), (prev.get("me") or {}).get("life")
            exact = False
        if not opp_life or opp_life <= 0 or my_life is None:
            continue
        avail = [c for c in mine if c[1] is not None and (c[1] or 0) > 0 and not c[3]
                 and not (len(c) > 6 and c[6]) and "defender" not in kw(c[0])]
        blockers = [c for c in theirs if c[1] is not None and not c[3]]
        if not avail:
            continue
        att = [a for a in (combat.get(str(t)) or {}).get("att", []) if a[2] == "me"]
        att_left = Counter(a[0] for a in att)
        used, held = [], []
        for c in avail:
            if att_left[c[0]] > 0:
                att_left[c[0]] -= 1
                used.append(c)
            else:
                held.append(c)
        opp_after = (now.get("opp") or {}).get("life")
        survived = opp_after is not None and opp_after > 0
        total = sum(c[1] or 0 for c in avail)
        worst_all = worst_case(avail, blockers)
        note = "" if exact else " (estimated from the previous turn's board)"

        if held and survived and worst_all >= opp_life:
            out.append({"t": t, "kind": "missed",
                        "text": f"Missed lethal: attacking with everything ({total} power into {len(blockers)} possible "
                                f"blocker{'s' if len(blockers) != 1 else ''}) gets at least {worst_all} through vs their "
                                f"{opp_life} life{note}."})
        elif held and survived and total >= opp_life and len(used) < len(avail):
            out.append({"t": t, "kind": "info",
                        "text": f"Possible lethal: you had {total} power vs their {opp_life} life, but blocks could stop "
                                f"it{note}. Worth checking for evasion or a pump spell."})

        # safe attacks held back
        opp_power = sum(c[1] or 0 for c in theirs if c[1] is not None)
        safe = []
        for c in held:
            if all(not can_block(b, c) or ((b[1] or 0) < (c[2] or 0) and "deathtouch" not in kw(b[0]))
                   for b in blockers):
                safe.append(c)
        # Their commander is locked down by your aura (Witness Protection, etc.). Chip damage
        # lets them chump-block with it, send it to the command zone and recast it fresh,
        # so holding back until you have lethal is the right play, not a missed attack.
        locked = [c for c in theirs if c[0] in opp_cmds and c[1] is not None]
        if not any(NEUTER_RE.search((cards.get(c[0]).get("oracle") or "").lower()) for c in mine if c[1] is None):
            locked = []
        if safe and locked and worst_all < opp_life:
            if not said_locked:
                said_locked.append(t)
                out.append({"t": t, "kind": "info",
                            "text": f"Held back while {name(locked[0][0])} was locked down by your aura: attacking "
                                    f"before you had lethal would let them chump-block with it and recast it fresh. Good discipline."})
            safe = []
        if safe and survived and opp_power < my_life * 0.5:
            dmg = sum(c[1] or 0 for c in safe)
            out.append({"t": t, "kind": "missed",
                        "text": f"Free damage skipped: {', '.join(name(c[0]) for c in safe)} could have attacked with no "
                                f"blocker able to kill {'it' if len(safe) == 1 else 'them'} (up to +{dmg}), and their board "
                                f"({opp_power} power) wasn't a threat to your {my_life} life{note}."})

        # attackers lost in combat
        rem = [r for r in m.get("removals", []) if r["t"] == t]
        used_grps = Counter(c[0] for c in used)
        for r in rem:
            if r["side"] == "me" and r["how"] == "Died to damage" and r.get("by_side") == "opp" and used_grps[r["g"]] > 0:
                traded = any(r2["side"] == "opp" and r2["g"] == r.get("by") for r2 in rem)
                if traded:
                    out.append({"t": t, "kind": "info", "text": f"Traded {name(r['g'])} for {name(r['by'])} in combat."})
                else:
                    out.append({"t": t, "kind": "bad",
                                "text": f"Lost {name(r['g'])} attacking into {name(r['by'])} without killing it."})

        # swing-back: would keeping the attackers home have blocked enough to matter?
        if used and nxt and nxt.get("a") == "opp":
            life_then = (now.get("me") or {}).get("life")
            life_next = (nxt.get("me") or {}).get("life")
            home = [c for c in used if "vigilance" not in kw(c[0])]
            their_att = [a for a in (combat.get(str(t + 1)) or {}).get("att", []) if a[2] == "opp"]
            if life_then is not None and life_next is not None and home and their_att:
                taken = life_then - life_next
                pool = sorted(their_att, key=lambda a: -(a[1] or 0))
                prevented = 0
                for c in sorted(home, key=lambda c: -(c[2] or 0)):
                    a = next((a for a in pool if can_block(c, a)), None)
                    if a is None:
                        continue
                    pool.remove(a)
                    prevented += a[1] or 0
                prevented = min(prevented, taken)
                would_live = life_next <= 0 < life_next + prevented
                if prevented >= 3 and (would_live or (prevented >= 0.4 * taken and taken >= max(6, 0.25 * life_then))):
                    out.append({"t": t, "kind": "bad" if would_live else "risky",
                                "text": (f"Attacking cost you the game: you died on their next turn, but keeping "
                                         if would_live else f"Your attack left you open: you took {taken} on their next turn; keeping ")
                                        + f"{', '.join(name(c[0]) for c in home)} home could have blocked about {prevented} of it."})

        dealt = opp_life - (opp_after if opp_after is not None else opp_life)
        if used and dealt >= max(5, 0.25 * opp_life):
            out.append({"t": t, "kind": "good",
                        "text": f"Strong attack: {dealt} damage ({opp_life} → {max(opp_after, 0)})."})
    return out


# ------------------------------------------------------------------ the "brain": learned from your own games
WP_FEATURES = ["base", "life_diff", "my_life", "opp_life", "power_diff", "creature_diff",
               "hand_diff", "land_diff", "my_cmd_out", "opp_cmd_out", "turn"]
WP_LABELS = {"life_diff": "Life lead", "my_life": "Your life", "opp_life": "Their life",
             "power_diff": "Board power lead", "creature_diff": "More creatures", "hand_diff": "More cards in hand",
             "land_diff": "More lands", "my_cmd_out": "Zimone on the battlefield",
             "opp_cmd_out": "Their commander out", "turn": "Later in the game"}


def wp_features(row, my_cmd_out, opp_cmd_out, turn):
    me, op = row.get("me") or {}, row.get("opp") or {}
    clip = lambda v, hi: max(-hi, min(hi, v or 0))
    ml, ol = me.get("life") or 0, op.get("life") or 0
    return [1.0, clip(ml - ol, 40) / 10, clip(ml, 60) / 25, clip(ol, 60) / 25,
            clip(clip(me.get("power"), 60) - clip(op.get("power"), 60), 40) / 10,
            clip((me.get("creatures") or 0) - (op.get("creatures") or 0), 10) / 3,
            clip((me.get("hand") or 0) - (op.get("hand") or 0), 10) / 3,
            clip((me.get("lands") or 0) - (op.get("lands") or 0), 10) / 3,
            my_cmd_out, opp_cmd_out, min(turn, 30) / 10]


def game_rows(m):
    board = m.get("board") or {}
    mc, oc = set(m.get("my_commanders") or []), set(m.get("opp_commanders") or [])
    on = lambda lst, ids: 1.0 if any(p[0] in ids and p[1] is not None for p in lst) else 0.0
    rows = []
    for x in m.get("timeline") or []:
        b = board.get(str(x["t"])) or {}
        rows.append((x["t"], wp_features(x, on(b.get("me", []), mc), on(b.get("opp", []), oc), x["t"])))
    return rows


def _sig(z):
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def train_winprob(matches):
    """Logistic regression on every turn of every finished game (each game weighted equally)."""
    data = []
    for m in matches:
        if m.get("result") not in ("Win", "Loss"):
            continue
        rows = game_rows(m)
        if not rows:
            continue
        y, w = (1.0 if m["result"] == "Win" else 0.0), 1.0 / len(rows)
        data += [(f, y, w) for _, f in rows]
    if len(data) < 60:
        return None
    n, beta = len(WP_FEATURES), [0.0] * len(WP_FEATURES)
    W = sum(w for _, _, w in data)
    lam, lr = 0.03, 0.8
    for _ in range(350):
        g = [0.0] * n
        for f, y, w in data:
            d = (_sig(sum(b * x for b, x in zip(beta, f))) - y) * w
            for i in range(n):
                g[i] += d * f[i]
        for i in range(n):
            beta[i] -= lr * (g[i] / W + (lam * beta[i] if i else 0))
    return beta


def get_winmodel(matches):
    done = sum(1 for m in matches if m.get("result") in ("Win", "Loss"))
    cached = load_json(MODEL_FILE, {})
    if cached.get("games") == done and cached.get("features") == WP_FEATURES:
        return cached
    beta = train_winprob(matches)
    if beta is None:
        return {}
    model = {"games": done, "features": WP_FEATURES, "beta": [round(b, 4) for b in beta]}
    try:
        save_json(MODEL_FILE, model)
    except OSError:
        pass
    return model


def threat_ranking(matches):
    """How much each opposing card has hurt you per game it showed up in."""
    seen, dmg, kills = Counter(), Counter(), Counter()
    for m in matches:
        opp = set(m.get("opp_seen") or []) | {p["g"] for p in m.get("plays", []) if p["side"] == "opp"}
        for g in opp:
            seen[g] += 1
        for g, v in ((m.get("damage") or {}).get("opp") or {}).get("to_player", {}).items():
            dmg[int(g)] += v
        for r in m.get("removals", []):
            if r["side"] == "me" and r.get("by_side") == "opp" and r.get("by"):
                kills[r["by"]] += 1
    out = {}
    for g in set(dmg) | set(kills):
        n = max(1, seen[g])
        out[str(g)] = [round((dmg[g] + 4 * kills[g]) / n, 1), seen[g]]
    return out


def wipe_turns(m):
    per = Counter(r["t"] for r in m.get("removals", [])
                  if r["side"] == "me" and r.get("creature") and r.get("by_side") == "opp")
    return sorted(t for t, n in per.items() if n >= 3)


OPP_PROFILE = {}  # read by the overlay: what decks of each colour have done to you
CRAFT_FILE = os.path.join(HERE, "craft.json")
RARITY_COST = {"common": 0, "uncommon": 1, "rare": 2, "mythic": 3}
CRAFT_QUERIES = {
    "flyers": ("Flyers", '(o:"creature with flying" (o:destroy or o:exile or o:damage)) or (t:creature kw:reach pow>=3)'),
    "neutralise": ("Threats you can't let die (Dina-style)",
                   '(o:"loses all abilities" or o:"exile target creature" or o:"exile target nonland" '
                   'or o:"return target creature" or o:"return target nonland")'),
    "wipes": ("Board wipes", '(o:"counter target spell" or o:"counter target noncreature") or '
                             '(o:"creatures you control" (o:hexproof or o:indestructible))'),
    "bombs": ("Big finishers and commanders", '(o:"counter target spell" or o:"counter target creature spell" '
                                              'or o:"exile target creature" or o:"return target nonland")'),
}


def loss_threats(matches, cards):
    """What keeps beating you, counted over your last 30 losses."""
    losses = [m for m in matches if m.get("result") == "Loss"][-30:]
    out = Counter()
    for m in losses:
        dmg = ((m.get("damage") or {}).get("opp") or {}).get("to_player", {})
        tot = sum(dmg.values()) or 1
        fly = sum(v for g, v in dmg.items() if "flying" in (cards.get(int(g)).get("kw") or []))
        cmd = sum(v for g, v in dmg.items() if int(g) in set(m.get("opp_commanders") or []))
        if fly / tot >= 0.35:
            out["flyers"] += 1
        if cmd / tot >= 0.4:
            out["neutralise"] += 1
        if wipe_turns(m):
            out["wipes"] += 1
        if any(p["side"] == "opp" and p["k"] == "spell" and (cards.get(p["g"]).get("cmc") or 0) >= 6
               for p in m.get("plays", [])):
            out["bombs"] += 1
    return out, len(losses)


def craft_suggestions(matches, cards, deck_names):
    """Arena-legal Simic cards that answer what beats you, cheapest wildcard first. Refreshed daily."""
    today = datetime.now().strftime("%Y-%m-%d")
    cached = load_json(CRAFT_FILE, {})
    threats, n = loss_threats(matches, cards)
    if cached.get("date") == today and cached.get("losses") == n:
        return cached
    res = {"date": today, "losses": n, "groups": []}
    for key, cnt in threats.most_common():
        label, q = CRAFT_QUERIES[key]
        query = f"id<=ug game:arena legal:brawl -t:land ({q})"
        try:
            req = urllib.request.Request("https://api.scryfall.com/cards/search?order=edhrec&q=" + urllib.parse.quote(query),
                                         headers={"User-Agent": "ArenaTracker/2.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.load(r).get("data", [])[:60]
            time.sleep(0.15)
        except Exception:
            continue
        picks = []
        for i, d in enumerate(data):
            info = scry_info(d)
            if info["name"].lower() in deck_names or (info["cmc"] or 0) > 5:
                continue
            info["popularity"] = i
            picks.append(info)
        # most-played answers first, with a nudge towards cheaper wildcards
        picks.sort(key=lambda c: c["popularity"] + 6 * RARITY_COST.get(c.get("rarity"), 2))
        res["groups"].append({"key": key, "label": label, "losses": cnt,
                              "cards": [{k: c.get(k) for k in ("name", "rarity", "mana", "cmc", "type", "img", "url", "oracle")}
                                        for c in picks[:6]]})
    if res["groups"]:
        save_json(CRAFT_FILE, res)
    return res


def backup_history(matches):
    """A weekly copy of your games, plus one file per finished season (month)."""
    bdir, adir = os.path.join(HERE, "backups"), os.path.join(HERE, "seasons")
    os.makedirs(bdir, exist_ok=True)
    os.makedirs(adir, exist_ok=True)
    week = datetime.now().strftime("%G-W%V")
    path = os.path.join(bdir, f"matches-{week}.json")
    if not os.path.exists(path) and os.path.exists(MATCHES_FILE):
        import shutil
        shutil.copyfile(MATCHES_FILE, path)
        old = sorted(f for f in os.listdir(bdir) if f.startswith("matches-"))[:-12]
        for f in old:
            try:
                os.remove(os.path.join(bdir, f))
            except OSError:
                pass
    this_month = datetime.now().strftime("%Y-%m")
    by_month = defaultdict(list)
    for m in matches:
        if m.get("start"):
            by_month[datetime.fromtimestamp(m["start"] / 1000).strftime("%Y-%m")].append(m)
    for month, ms in by_month.items():
        f = os.path.join(adir, f"season-{month}.json")
        if month != this_month and not os.path.exists(f):
            save_json(f, ms)


def build_outputs(store, cards):
    matches = sorted(store.values(), key=lambda m: m["start"])
    for m in matches:
        for k in ("my_commanders", "opp_commanders"):
            kept = [g for g in m.get(k, []) if "Dungeon" not in cards.get(g).get("type", "")]
            if kept:
                m[k] = kept
    ids = set()
    for m in matches:
        ids.update(m["my_commanders"], m["opp_commanders"], m["opp_seen"])
        ids.update(p["g"] for p in m.get("plays", []))
        for h in m.get("hands", []):
            ids.update(h)
        ids.update(d[1] for d in m.get("draws", []))
        for r in m.get("removals", []):
            ids.add(r["g"])
            if r.get("by"):
                ids.add(r["by"])
        for sd in (m.get("damage") or {}).values():
            ids.update(int(g) for g in sd.get("to_player", {}))
            ids.update(int(g) for g in sd.get("to_creature", {}))
        for b in (m.get("board") or {}).values():
            ids.update(c[0] for k in ("me", "opp") for c in b.get(k, []))
            ids.update(b.get("hand", []))
        for u in m.get("cmd_uses") or []:
            ids.update(u.get("targets", []))
        for c in m.get("countered") or []:
            ids.add(c["g"])
            if c.get("by"):
                ids.add(c["by"])
        for pc in (m.get("precombat") or {}).values():
            ids.update(c[0] for k in ("me", "opp") for c in pc.get(k, []))
        for c in (m.get("combat") or {}).values():
            ids.update(a[0] for a in c.get("att", []))
            ids.update(bl[0] for bl in c.get("blk", []))
        ids.update((m.get("deck") or {}).get("cards", []))
    names = {str(i): cards.get(i) for i in sorted(ids)}
    cards.save()

    abil_info = {}
    freq_by_src = defaultdict(Counter)  # across all games: the most frequent ability per commander is its trigger
    for m in matches:
        for u in m.get("cmd_uses") or []:
            freq_by_src[u["src"]][u["ab"]] += 1
    for m in matches:
        uses = m.get("cmd_uses") or []
        for u in uses:
            freq = freq_by_src[u["src"]]
            txt = cards.ability_text(u["ab"])
            if txt:
                kind = "activated" if re.search(r"^[^.]*?(\{[^}]+\}|tap|\{T\}).*?:", txt) and not re.match(r"(when|whenever|at the beginning)", txt.lower()) else "triggered"
            else:  # no text available: the once-per-combat one is the trigger
                kind = "triggered" if freq[u["ab"]] >= max(freq.values()) and len(freq) > 1 else "activated"
            u["kind"] = kind
            abil_info[str(u["ab"])] = {"text": txt, "kind": kind}

    latest_deck = next((m.get("deck", {}).get("cards") for m in reversed(matches) if m.get("deck", {}).get("cards")), [])
    for m in matches:
        try:
            m["interaction"] = review_interaction(m, cards, (m.get("deck") or {}).get("cards") or latest_deck)
        except Exception as e:
            m["interaction"] = {}
            log(f"Interaction review failed for a game: {e!r}")

    for m in matches:
        try:
            m["attack_review"] = analyze_attacks(m, cards)
        except Exception as e:
            m["attack_review"] = []
            log(f"Attack review failed for a game: {e!r}")

    for m in matches:
        iv = m.get("interaction") or {}
        for x in iv.get("let_through", []):
            names.setdefault(str(x["g"]), cards.get(x["g"]))
            for h in x["held"]:
                names.setdefault(str(h), cards.get(h))
        sb = iv.get("saved_by") or {}
        for h in sb.get("answers", []):
            names.setdefault(str(h), cards.get(h))
    if matches:
        last = matches[-1]
        if last.get("end", 0) != LAST_RECAP.get("match_end"):  # shown by the overlay when a game just ended
            LAST_RECAP.update({"match_end": last.get("end", 0), "lines": make_recap(last, cards)})

    # mulligan advisor
    by_lands, by_lr = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for m in matches:
        if not m.get("kept") or m["result"] not in ("Win", "Loss"):
            continue
        f = hand_features(m["kept"], cards)
        m["hand_f"] = f
        i = 0 if m["result"] == "Win" else 1
        by_lands[f["lands"]][i] += 1
        by_lr[f"{f['lands']}|{1 if f['ramp'] else 0}"][i] += 1
    mull = [0, 0]
    for m in matches:
        if m.get("mulligans") and m["result"] in ("Win", "Loss"):
            mull[0 if m["result"] == "Win" else 1] += 1
    ADVISOR.clear()
    ADVISOR.update({"by_lands": dict(by_lands), "by_lands_ramp": dict(by_lr), "mull": mull})

    # opponent scouting
    SCOUT.clear()
    for m in matches:
        key = "-".join(map(str, m["opp_commanders"]))
        if not key:
            continue
        sc = SCOUT.setdefault(key, {"w": 0, "l": 0, "cards": Counter(), "threat": Counter()})
        if m["result"] == "Win":
            sc["w"] += 1
        elif m["result"] == "Loss":
            sc["l"] += 1
        for g in {p["g"] for p in m.get("plays", []) if p["side"] == "opp" and p["k"] == "spell"}:
            if g not in m["opp_commanders"]:
                sc["cards"][g] += 1
        for r in m.get("removals", []):
            if r["side"] == "me" and r.get("by_side") == "opp" and r.get("by"):
                sc["threat"][r["by"]] += 3
        for g, v in ((m.get("damage") or {}).get("opp") or {}).get("to_player", {}).items():
            sc["threat"][int(g)] += v / 3

    # upgrade checklist
    upgrades = load_json(UPGRADES_FILE, None)
    if upgrades is None:
        upgrades = DEFAULT_UPGRADES
        save_json(UPGRADES_FILE, upgrades)
    decks = load_json(DECKS_FILE, [])
    cur_id = next((m.get("deck", {}).get("id") for m in reversed(matches) if m.get("deck", {}).get("id")), None)
    mine = [d for d in decks if d["id"] == cur_id] or decks
    latest = mine[-1]["cards"] if mine else next(
        (m.get("deck", {}).get("cards") for m in reversed(matches) if m.get("deck", {}).get("cards")), [])
    for d in decks:
        ids_extra = set(d["cards"]) | set(d.get("commanders", []))
        for g in ids_extra:
            names.setdefault(str(g), cards.get(g))
    cards.ensure_rarity(set(latest))
    for g in set(latest):
        names[str(g)] = cards.get(g)
    in_deck = {cards.get(g)["name"].lower() for g in latest}
    in_deck |= {n.split(" // ")[0] for n in in_deck}
    upgrade_cards = {}
    try:
        owned = owned_names(cards, matches)
    except Exception as e:
        log(f"Owned cards skipped ({e!r}).")
        owned = set()
    for st in upgrades.get("stages", []):
        st["done"] = [c for c in st.get("cards", []) if c.lower() in in_deck]
        st["owned"] = [c for c in st.get("cards", []) if c.lower() not in in_deck and c.lower() in owned]
        for c in st.get("cards", []):
            upgrade_cards[c] = cards.by_name(c)
    try:
        craft = craft_suggestions(matches, cards, in_deck | owned)
    except Exception as e:
        log(f"Craft suggestions skipped ({e!r}).")
        craft = {}
    cards.save()
    wildcards = load_json(WILDCARDS_FILE, [])

    model = get_winmodel(matches)
    if model.get("beta"):
        for m in matches:
            m["wp"] = [[t, round(_sig(sum(b * x for b, x in zip(model["beta"], f))), 3)] for t, f in game_rows(m)]
    threats = threat_ranking(matches)
    try:
        backup_history(matches)
    except OSError as e:
        log(f"Backup skipped ({e!r}).")

    def label(cmd_ids):
        n = [names[str(i)]["name"] for i in cmd_ids]
        col = "".join(c for c in "WUBRG" if any(c in names[str(i)]["colors"] for i in cmd_ids))
        return " + ".join(n) or "Unknown", col or "C"

    out = []
    OPP_PROFILE.clear()
    deck_names = {d["id"]: d.get("name") for d in decks}

    def colours_of(ids):
        """Colours of the non-land cards seen, for decks without a commander (constructed formats)."""
        out = set()
        for g in ids:
            c = names.get(str(g)) or cards.get(g)
            names.setdefault(str(g), c)
            if "Land" not in (c.get("type") or ""):
                out |= set(c.get("colors") or "")
        return "".join(x for x in "WUBRG" if x in out) or "C"

    for m in matches:
        if m["opp_commanders"]:
            opp_cmd, opp_col = label(m["opp_commanders"])
        else:
            opp_col = colours_of(m.get("opp_seen") or [])
            opp_cmd = GUILDS.get(opp_col, opp_col)
        if m["my_commanders"]:
            my_cmd, _ = label(m["my_commanders"])
        else:
            dk = m.get("deck") or {}
            my_cmd = deck_names.get(dk.get("id")) or GUILDS.get(colours_of(dk.get("cards") or []), "Your deck")
        r = dict(m)
        r.pop("my_user_id", None)
        r.pop("opp_seen", None)
        r.update({
            "date": datetime.fromtimestamp(m["start"] / 1000).strftime("%Y-%m-%d %H:%M") if m["start"] else "",
            "event_name": EVENT_NAMES.get(m["event"], m["event"]),
            "my_cmd": my_cmd, "opp_cmd": opp_cmd, "opp_colors": opp_col,
        })
        out.append(r)
        if m["result"] in ("Win", "Loss"):
            pr = OPP_PROFILE.setdefault(opp_col, {"games": 0, "w": 0, "l": 0, "wiped": 0, "countered": 0})
            pr["games"] += 1
            pr["w" if m["result"] == "Win" else "l"] += 1
            pr["wiped"] += 1 if wipe_turns(m) else 0
            pr["countered"] += 1 if any(c.get("side") == "me" for c in m.get("countered", [])) else 0

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "event", "result", "reason", "turns", "on_play", "mulligans",
                    "my_commander", "opponent", "opp_commander", "opp_colors",
                    "my_final_life", "opp_final_life", "my_life_lost", "opp_life_lost",
                    "my_spells", "opp_spells"])
        for r in out:
            plays = r.get("plays", [])
            w.writerow([r["date"], r["event_name"], r["result"], r["reason"], r["turns"],
                        r.get("on_play"), r.get("mulligans"), r["my_cmd"], r["opp_name"],
                        r["opp_cmd"], r["opp_colors"], r.get("my_life"), r.get("opp_life"),
                        r.get("life_lost", {}).get("me"), r.get("life_lost", {}).get("opp"),
                        sum(p["side"] == "me" and p["k"] == "spell" for p in plays),
                        sum(p["side"] == "opp" and p["k"] == "spell" for p in plays)])

    data = {"generated": datetime.now().strftime("%d %b %Y %H:%M"),
            "matches": out, "cards": names, "upgrades": upgrades,
            "wildcards": wildcards, "decks": decks, "current_deck": cur_id,
            "upgrade_cards": upgrade_cards, "abilities": abil_info,
            "winmodel": model, "wp_labels": WP_LABELS, "threats": threats, "craft": craft,
            # private-tracker features that aren't in MTGASIM, kept empty so the page renders without them
            "videos": {}, "compilations": [], "replays": {}, "lan_url": "", "feedback": [], "nn": {}, "net": None}
    save_json(DATA_FILE, data)
    wins = sum(r["result"] == "Win" for r in out)
    return wins, sum(r["result"] == "Loss" for r in out)


def _strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "")


def owned_names(cards, matches):
    """Lower-case names of cards you own, as far as the log shows: anything in a deck you've played."""
    out = set()
    col = (load_json(COLLECTION_FILE, {}) or {}).get("cards") or {}
    for g, n in col.items():
        if n:
            nm = cards.local_name(str(g)) or (cards.cache.get(str(g)) or {}).get("name")
            if nm:
                nm = _strip_tags(nm).lower()
                out.add(nm)
                out.add(nm.split(" // ")[0])
    for m in matches:
        for g in ((m.get("deck") or {}).get("cards") or []) + list(m.get("my_commanders") or []):
            nm = (cards.cache.get(str(g)) or {}).get("name")
            if nm:
                out.add(nm.lower())
                out.add(nm.lower().split(" // ")[0])
    return out


def read_file(path, parser, start=0):
    """Feed complete lines from `start`; return the offset after the last full line."""
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read()
    end = data.rfind(b"\n")
    if end < 0:
        return start
    for raw in data[:end].split(b"\n"):
        parser.feed(raw.decode("utf-8", "ignore"))
    return start + end + 1



# ------------------------------------------------------------------ live overlay

def _log_size():
    """Real length of Player.log. Windows can report a stale size for a file Arena has open,
    so ask through an open handle instead of trusting the directory entry."""
    with open(LOG, "rb") as f:
        return f.seek(0, 2)
