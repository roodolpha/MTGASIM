"""Keeps Brewbench's deck folder in step with your Arena collection.

Arena writes every deck you own (cards, commander, format) to its log when it starts, and each save after
that. sync() turns those into .dck files, one per Arena deck, tagged with the format so the right gauntlet
is picked. Arena's starter/precon decks and formats Forge can't play are left out. Re-running it updates
decks you've edited in Arena; decks you remove in Brewbench stay removed."""
import threading

from . import arena_log, cards, decks as D, gauntlet

_lock = threading.Lock()
_last = {"key": None, "result": None}


def _log_key(paths):
    import os
    try:
        return tuple((str(p), os.path.getmtime(p), os.path.getsize(p)) for p in paths)
    except OSError:
        return None


def existing(cfg):
    """{arena_id: path} for decks already imported."""
    out = {}
    for p in cfg.decks_dir.glob("*.dck"):
        d = D.read_dck(p)
        if d.arena_id:
            out[d.arena_id] = p
    return out


def to_deck(cd, book):
    deck = D.Deck(name=cd.name, format=cd.format or "", arena_id=cd.deck_id)
    for g in cd.commanders:
        deck.commanders.append(D.clean_name(book.name(g) or f"#{g}"))
    for g in cd.main:
        deck.main[D.clean_name(book.name(g) or f"#{g}")] += 1
    for g in cd.side:
        deck.side[D.clean_name(book.name(g) or f"#{g}")] += 1
    return deck


def sync(cfg, force=False):
    """Import new Arena decks and refresh changed ones. Cheap when the logs haven't changed.
    Returns {"added": [...], "updated": [...], "skipped": n, "error": str|None}."""
    if cfg.get("arena_decks", True) is False:
        return {"added": [], "updated": [], "skipped": 0, "error": None, "off": True}
    with _lock:
        paths = arena_log.find_logs(cfg.get("arena_log"))
        if not paths:
            return {"added": [], "updated": [], "skipped": 0, "error": "Arena's log wasn't found"}
        key = _log_key(paths)
        if not force and key and key == _last["key"]:
            return _last["result"]
        coll = arena_log.collection(paths)
        removed = set(cfg.get("arena_removed") or [])
        have = existing(cfg)
        book = cards.CardBook(cfg.cache_dir / "cards.json")
        added, updated, skipped = [], [], 0
        for cd in sorted(coll.values(), key=lambda d: d.updated):
            if cd.precon or not cd.format or not cd.main or cd.deck_id in removed:
                skipped += 1
                continue
            deck = to_deck(cd, book)
            text = deck.to_dck()
            path = have.get(cd.deck_id)
            if path is None:
                base = gauntlet.slug(cd.name) or "arena-deck"
                path, n = cfg.decks_dir / f"{base}.dck", 2
                while path.exists():
                    path, n = cfg.decks_dir / f"{base}-{n}.dck", n + 1
                deck.save(path)
                added.append(cd.name)
            elif path.read_text(encoding="utf-8") != text:
                deck.save(path)
                updated.append(cd.name)
        book.save()
        result = {"added": added, "updated": updated, "skipped": skipped, "error": None}
        _last.update(key=key, result=result)
        return result


def remove(cfg, deck_id_stem):
    """Delete a deck file; if it came from Arena, remember not to bring it back."""
    p = cfg.decks_dir / f"{deck_id_stem}.dck"
    if not p.exists():
        return False
    d = D.read_dck(p)
    if d.arena_id:
        gone = set(cfg.get("arena_removed") or [])
        gone.add(d.arena_id)
        cfg.set("arena_removed", sorted(gone))
    p.unlink()
    return True


_bg = {"thread": None}


def sync_soon(cfg):
    """Start a sync in the background if one isn't running, so pages never wait on it."""
    t = _bg["thread"]
    if t is not None and t.is_alive():
        return False

    def run():
        try:
            sync(cfg)
        except Exception:   # logged by the caller's next foreground sync; never kill the server
            pass
    _bg["thread"] = threading.Thread(target=run, name="arena-deck-sync", daemon=True)
    _bg["thread"].start()
    return True


def busy():
    t = _bg["thread"]
    return bool(t and t.is_alive())
