"""Opponent decks to test against.

A gauntlet is a folder of .dck files (gauntlets/<format>/). You can fill it three ways:
  * drop in decklists yourself (Arena export text or .dck) with `brewbench gauntlet add`
  * Brawl: build one deck per commander you've faced, from your Arena log (cards you saw them play,
    optionally topped up with EDHREC's average list for that commander: off unless you turn it on)
  * later phases: meta decklists from public sources (see docs/ROADMAP.md)
"""
import json
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

from . import decks as D

UA = {"User-Agent": "Brewbench/0.1 (+https://github.com/roodolpha/brewbench)", "Accept": "application/json"}
BASIC_FOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


def slug(name):
    n = D.clean_name(name).lower()
    n = re.sub(r"[',.!?\"]", "", n)
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-")


def list_decks(folder):
    return sorted(Path(folder).glob("*.dck"))


def expand_sources(sources):
    """Files, folders (every .txt/.dck inside) or pasted text."""
    out = []
    for s in sources:
        p = Path(s)
        if p.is_dir():
            out += sorted(x for x in p.iterdir() if x.suffix.lower() in (".txt", ".dck"))
        else:
            out.append(s)
    return out


def add(folder, source, name=None):
    deck = D.load(source, name)
    if name:
        deck.name = name
    path = Path(folder) / f"{slug(deck.name) or 'deck'}.dck"
    return deck.save(path), deck


def _get(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def edhrec_cards(commander):
    """EDHREC's average deck for a commander, then its most-included cards. [] if unavailable."""
    s = slug(commander)
    cards = []
    try:
        d = _get(f"https://json.edhrec.com/pages/average-decks/{s}.json")
        for lst in (d.get("deck") or {}).get("cards", {}).values():
            cards += [n for n, _ in lst]
    except Exception:
        pass
    try:
        d = _get(f"https://json.edhrec.com/pages/commanders/{s}.json")
        views = []
        for cl in d["container"]["json_dict"]["cardlists"]:
            views += cl.get("cardviews", [])
        views.sort(key=lambda c: -(c.get("inclusion") or c.get("num_decks") or 0))
        cards += [c["name"] for c in views]
    except Exception:
        pass
    return cards


def scryfall_identity(names):
    """{name: (colour identity, type line, brawl legality, on arena)} via Scryfall's collection endpoint."""
    out = {}
    names = list(dict.fromkeys(names))
    for i in range(0, len(names), 75):
        body = json.dumps({"identifiers": [{"name": n} for n in names[i:i + 75]]}).encode()
        req = urllib.request.Request("https://api.scryfall.com/cards/collection", data=body,
                                     headers=dict(UA, **{"Content-Type": "application/json"}))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        for c in d.get("data", []):
            tl = c.get("type_line") or (c.get("card_faces") or [{}])[0].get("type_line", "")
            v = ("".join(c.get("color_identity") or []), tl, (c.get("legalities") or {}).get("brawl"),
                 "arena" in (c.get("games") or []))
            out[c["name"]] = v
            out.setdefault(c["name"].split(" // ")[0], v)
        time.sleep(0.1)
    return out


def brawl_deck(commander, seen, forge_names, size=99, use_edhrec=True):
    """A 99-card Brawl list for an opponent's commander: what you saw them play first, then EDHREC's
    average list, then basics. Only cards that are Brawl-legal, on Arena, in Forge and in colour identity."""
    pool = list(dict.fromkeys([commander] + list(seen) + (edhrec_cards(commander) if use_edhrec else [])))
    info = scryfall_identity(pool)
    ci = set((info.get(commander) or ("",))[0])
    ok = lambda n: (n in info and n in forge_names and n != commander and info[n][2] == "legal"
                    and info[n][3] and set(info[n][0]) <= ci and n not in D.BASICS)
    is_land = lambda n: "Land" in info[n][1].split(" // ")[0]
    chosen = []
    for n in pool:
        n = D.clean_name(n)
        if n not in chosen and ok(n):
            chosen.append(n)
    nonland = [n for n in chosen if not is_land(n)][:62]
    lands = [n for n in chosen if is_land(n)][:20]
    deck = D.Deck(name=commander, commanders=[commander])
    for n in nonland + lands:
        deck.main[n] = 1
    cols = [c for c in "WUBRG" if c in ci] or ["C"]
    i = 0
    while deck.size < size:
        deck.main[BASIC_FOR.get(cols[i % len(cols)], "Wastes")] += 1
        i += 1
    return deck


def from_log(reader, book, folder, forge_names, events=("Brawl",), log=print, use_edhrec=False):
    """One deck per opposing commander in your Arena log (Brawl events only)."""
    seen, faced = {}, Counter()
    for m in reader.matches.values():
        if not any(e.lower() in (m.event or "").lower() for e in events):
            continue
        for g in m.opp_commanders:
            c = book.name(g)
            if not c:
                continue
            c = D.clean_name(c)
            faced[c] += 1
            seen.setdefault(c, Counter()).update(
                D.clean_name(n) for n in (book.name(x) for x in m.opp_seen) if n)
    book.save()
    made = []
    for c, n in faced.most_common():
        if c not in forge_names:
            log(f"  skipped {c}: Forge doesn't have it")
            continue
        deck = brawl_deck(c, [x for x, _ in seen[c].most_common()], forge_names, use_edhrec=use_edhrec)
        path = deck.save(Path(folder) / f"{slug(c)}.dck")
        made.append((path, n))
        log(f"  {c} (faced {n}x)")
    return made
