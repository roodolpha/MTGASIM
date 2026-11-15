"""Reads MTG Arena's Player.log: the decks you've saved or queued with, and the matches you've played
(your deck, the opponent's cards you saw, the result). Reading the log is all MTGASIM does with Arena:
it never touches the game client or its memory.

Arena only writes the detail we need when "Detailed Logs (Plugin Support)" is on
(Options > Account > Detailed Logs)."""
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


def default_log_paths():
    home = Path.home()
    return [
        home / "AppData" / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log",          # Windows
        home / "AppData" / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player-prev.log",
        home / "Library" / "Logs" / "Wizards Of The Coast" / "MTGA" / "Player.log",               # macOS
        home / "Library" / "Logs" / "Wizards Of The Coast" / "MTGA" / "Player-prev.log",
    ]


def find_logs(configured=None):
    if configured:
        return [Path(configured)] if Path(configured).exists() else []
    return [p for p in default_log_paths() if p.exists()]


@dataclass
class ArenaDeck:
    deck_id: str
    name: str
    cards: list            # grpIds, one entry per copy
    commanders: list
    saved: str = ""


@dataclass
class ArenaMatch:
    match_id: str
    event: str = ""
    start: int = 0
    my_seat: str = None
    my_deck: list = field(default_factory=list)
    my_commanders: list = field(default_factory=list)
    opp_seen: Counter = field(default_factory=Counter)   # grpId -> times seen (one per object)
    opp_commanders: set = field(default_factory=set)
    result: str = ""                                      # Win / Loss / Draw


def _json_tail(line):
    try:
        return json.loads(line[line.index("{"):])
    except ValueError:
        return None


class LogReader:
    def __init__(self):
        self.decks = {}        # (deck_id, card tuple) -> ArenaDeck: every distinct version
        self.matches = {}
        self._cur = None
        self._my_team = None
        self._pending = None   # Arena sends your deck (ConnectResp) just before the match's "Playing" event

    def feed(self, line):
        if "matchGameRoomStateChangedEvent" in line:
            self._room(line)
        elif "greToClientEvent" in line:
            if self._cur is not None:
                self._gre(line)
            elif "ConnectResp" in line:
                self._early_connect(line)
        elif "==> EventSetDeck" in line or "==> DeckUpsertDeck" in line:
            self._deck(line)

    def read(self, path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                self.feed(line)
        return self

    # -- decks you save or queue with
    def _deck(self, line):
        d = _json_tail(line)
        try:
            req = json.loads(d["request"]) if isinstance(d.get("request"), str) else d.get("request") or d
            summ = req.get("Summary", {})
            attrs = {a.get("name"): a.get("value") for a in summ.get("Attributes", [])}
            body = req.get("Deck") or {}
            cards = []
            for c in body.get("MainDeck", []):
                cards += [int(c["cardId"])] * int(c.get("quantity", 1))
            cmds = [int(c["cardId"]) for c in body.get("CommandZone", [])]
        except (TypeError, KeyError, ValueError, AttributeError):
            return
        if not cards:
            return
        key = (summ.get("DeckId", ""), tuple(sorted(cards)))
        self.decks[key] = ArenaDeck(summ.get("DeckId", ""), summ.get("Name", ""), sorted(cards), cmds,
                                    (attrs.get("LastUpdated") or "").strip('"')[:19])

    # -- matches
    def _room(self, line):
        d = _json_tail(line)
        if not d:
            return
        info = d.get("matchGameRoomStateChangedEvent", {}).get("gameRoomInfo", {})
        cfg = info.get("gameRoomConfig", {})
        mid = cfg.get("matchId")
        if not mid:
            return
        state = info.get("stateType", "")
        players = cfg.get("reservedPlayers", [])
        if state == "MatchGameRoomStateType_Playing":
            if self._cur is None or self._cur.match_id != mid:
                self._cur = self.matches.setdefault(mid, ArenaMatch(
                    mid, players[0].get("eventId", "") if players else "", int(d.get("timestamp", 0) or 0)))
                self._teams = {str(p["systemSeatId"]): p.get("teamId", p["systemSeatId"]) for p in players}
                if self._pending and not self._cur.my_deck:
                    self._cur.my_deck, self._cur.my_commanders, seat = self._pending
                    self._cur.my_seat = self._cur.my_seat or seat
                self._pending = None
        elif state == "MatchGameRoomStateType_MatchCompleted" and self._cur and self._cur.match_id == mid:
            winner = None
            for r in info.get("finalMatchResult", {}).get("resultList", []):
                if r.get("scope") == "MatchScope_Match":
                    winner = r.get("winningTeamId")
            me = self._cur.my_seat
            my_team = self._teams.get(me, int(me) if me and me.isdigit() else None) if me else None
            if winner is None or my_team is None:
                self._cur.result = "Draw"
            else:
                self._cur.result = "Win" if str(winner) == str(my_team) else "Loss"
            self._cur = None

    def _early_connect(self, line):
        d = _json_tail(line) or {}
        for msg in d.get("greToClientEvent", {}).get("greToClientMessages", []):
            dm = (msg.get("connectResp") or {}).get("deckMessage") or {}
            if dm.get("deckCards"):
                seats = msg.get("systemSeatIds") or []
                self._pending = (sorted(dm["deckCards"]), sorted(dm.get("commanderCards", [])),
                                 str(seats[0]) if len(seats) == 1 else None)

    def _gre(self, line):
        d = _json_tail(line)
        if not d:
            return
        cur = self._cur
        for msg in d.get("greToClientEvent", {}).get("greToClientMessages", []):
            seats = msg.get("systemSeatIds") or []
            if len(seats) == 1 and cur.my_seat is None:
                cur.my_seat = str(seats[0])
            if msg.get("type") == "GREMessageType_ConnectResp":
                dm = msg.get("connectResp", {}).get("deckMessage", {})
                if dm.get("deckCards"):
                    cur.my_deck = sorted(dm.get("deckCards", []))
                    cur.my_commanders = sorted(dm.get("commanderCards", []))
            gs = msg.get("gameStateMessage")
            if not gs or cur.my_seat is None:
                continue
            command_zones = {z["zoneId"] for z in gs.get("zones", [])
                             if z.get("type") == "ZoneType_Command" and str(z.get("ownerSeatId")) != cur.my_seat}
            for o in gs.get("gameObjects", []):
                if o.get("type") != "GameObjectType_Card" or not o.get("grpId"):
                    continue
                if str(o.get("ownerSeatId")) == cur.my_seat:
                    continue
                key = (o.get("instanceId"), o["grpId"])
                if key in getattr(cur, "_keys", set()):
                    continue
                if not hasattr(cur, "_keys"):
                    cur._keys = set()
                cur._keys.add(key)
                cur.opp_seen[o["grpId"]] += 1
                if o.get("zoneId") in command_zones:
                    cur.opp_commanders.add(o["grpId"])


def read_all(paths=None) -> LogReader:
    """Reads Player-prev.log then Player.log, so the last two sessions are covered."""
    r = LogReader()
    paths = paths or find_logs()
    for p in sorted(paths, key=lambda p: os.path.getmtime(p)):
        r.read(p)
    return r
