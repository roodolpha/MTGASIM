import json

from brewbench import arena_decks, arena_log, decks as D
from brewbench.config import Config


def _log(tmp_path, decks):
    summaries = [{"DeckIdInternal": i, "Name": n, "Attributes": [{"name": "Format", "value": f}]} for i, n, f, _, _ in decks]
    lists = {i: {"MainDeck": [{"cardId": c, "quantity": q} for c, q in main], "CommandZone": [{"cardId": cmd, "quantity": 1}] if cmd else []}
             for i, _, _, main, cmd in decks}
    p = tmp_path / "Player.log"
    p.write_text("<== StartHook(abc)\n" + json.dumps({"DeckSummaries": summaries, "DecksInternal": lists}) + "\n", encoding="utf-8")
    return p


class Book:
    def __init__(self, *a): pass
    def name(self, g): return {1: "Island", 2: "Opt", 9: "Zimone, Paradox Sculptor"}.get(g)
    def save(self): pass


def test_collection_reads_formats_and_skips_precons(tmp_path):
    p = _log(tmp_path, [("a", "COUNTRS", "HistoricBrawl", [(1, 98), (2, 1)], 9),
                        ("b", "?=?Loc/Decks/Precon/X", "Alchemy", [(1, 60)], None),
                        ("c", "Glad", "Gladiator", [(1, 99)], 9)])
    c = arena_log.collection([p])
    assert c["a"].format == "brawl" and not c["a"].precon and len(c["a"].main) == 99
    assert c["b"].precon and c["c"].format is None


def test_sync_imports_with_commander_counted_and_respects_removal(tmp_path, monkeypatch):
    p = _log(tmp_path, [("a", "COUNTRS", "HistoricBrawl", [(1, 98), (2, 1)], 9),
                        ("s", "Mono Blue", "Standard", [(1, 56), (2, 4)], None)])
    cfg = Config(tmp_path / "home")
    cfg.set("arena_log", str(p))
    monkeypatch.setattr(arena_decks.cards, "CardBook", Book)
    r = arena_decks.sync(cfg, force=True)
    assert sorted(r["added"]) == ["COUNTRS", "Mono Blue"]
    d = D.read_dck(cfg.decks_dir / "countrs.dck")
    assert d.total == 100 and d.size == 99 and d.format == "brawl" and d.arena_id == "a"
    assert arena_decks.sync(cfg, force=True)["added"] == []        # second run changes nothing
    assert arena_decks.remove(cfg, "countrs")
    assert arena_decks.sync(cfg, force=True)["added"] == []        # removed decks stay removed
