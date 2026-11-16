"""Card ideas for a Brawl deck from EDHREC: cards that decks with the same commander often play and yours doesn't.

Facts only: how many of EDHREC's decks for the commander run each card, and EDHREC's synergy score (how much
more often the card shows up with this commander than in other decks of its colours). EDHREC counts paper
Commander decks, so the list is filtered to cards legal in the Arena format the deck is for."""
import json
import time
import urllib.request

from . import cards as C, decks as D, gauntlet

CACHE_HOURS = 24
LIST_KINDS = {"newcards": "new", "topcards": "top", "highsynergycards": "synergy", "highliftcards": "lift"}


def _plain(header):
    """EDHREC's list headers ("Creatures", "Utility Artifacts") as one card type."""
    h = (header or "").lower()
    return next((k for k in ("Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment", "Land")
                 if k.lower() in h), None)


def _page(cfg, commander):
    """EDHREC's commander page JSON, cached for a day. Raises on failure with nothing cached."""
    s = gauntlet.slug(commander)
    path = cfg.cache_dir / "edhrec" / f"{s}.json"
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_HOURS * 3600:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        req = urllib.request.Request(f"https://json.edhrec.com/pages/commanders/{s}.json", headers=gauntlet.UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception:
        if path.exists():                       # stale beats nothing when EDHREC is down
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d), encoding="utf-8")
    return d


def for_deck(cfg, deck, fmt):
    """{"commander", "url", "decks", "cards": [{name, category, decks, share, synergy, tags}], "left_out"}."""
    if not deck.commanders:
        raise ValueError("Card ideas need a commander. This deck doesn't have one.")
    commander = deck.commanders[0]
    page = _page(cfg, commander)
    lists = ((page.get("container") or {}).get("json_dict") or {}).get("cardlists") or []
    have = {n.lower() for n in list(deck.main) + list(deck.commanders) + list(deck.side)}
    have |= {n.split(" // ")[0] for n in have}
    found, tags, most = {}, {}, 0
    for cl in lists:
        tag = cl.get("tag") or ""
        for v in cl.get("cardviews") or []:
            name = v.get("name")
            if not name:
                continue
            most = max(most, v.get("potential_decks") or 0)
            if tag in LIST_KINDS:
                tags.setdefault(name, []).append(LIST_KINDS[tag])
                if name in found:
                    continue
            elif name in found and found[name]["category"] is None:
                found[name]["category"] = cl.get("header")
                continue
            if name in found:
                continue
            found[name] = {"name": name, "category": None if tag in LIST_KINDS else cl.get("header"),
                           "decks": v.get("num_decks") or 0, "of": v.get("potential_decks") or 0,
                           "synergy": v.get("synergy")}
    cand = [c for n, c in found.items()
            if n.lower() not in have and n.split(" // ")[0].lower() not in have and n not in D.BASICS]
    legal = C.legality([c["name"] for c in cand], fmt.scryfall, cfg.cache_dir / "legality.json")
    checked = bool(legal) or not cand            # Scryfall unreachable: show everything, and say so
    out, left = [], 0
    for c in cand:
        if checked and legal.get(c["name"]) != "legal":
            left += 1
            continue
        c["share"] = c["decks"] / c["of"] if c["of"] else None
        c["tags"] = tags.get(c["name"], [])
        out.append(c)
    types = C.identity([c["name"] for c in out], cfg.cache_dir / "identity.json")
    for c in out:
        tl = (types.get(c["name"]) or {}).get("type") or ""
        c["category"] = next((k for k in ("Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact",
                                          "Enchantment", "Land") if k in tl), None) or _plain(c["category"]) or "Other"
    out.sort(key=lambda c: -(c["share"] or 0))
    return {"commander": commander, "decks": most, "cards": out, "left_out": left, "checked": checked,
            "url": f"https://edhrec.com/commanders/{gauntlet.slug(commander)}"}
