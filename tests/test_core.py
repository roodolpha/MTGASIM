import json
from pathlib import Path

from mtgasim import arena_log, decks as D, formats, runner, stats

ARENA_TEXT = """Commander
1 Zimone, Mightiest Wizard (DSK) 230

Deck
1 Sol Ring (CMM) 400
1 Delver of Secrets // Insectile Aberration (MID) 47
40 Island (ANB) 112
"""

STANDARD_TEXT = """4 Lightning Strike (M19) 152
20 Mountain (ANB) 114
2x Opt

2 Abrade (DMU) 114
"""


def test_parse_arena_brawl():
    d = D.parse_arena(ARENA_TEXT, "Zimone")
    assert d.commanders == ["Zimone, Mightiest Wizard"]
    assert d.main["Sol Ring"] == 1
    assert d.main["Delver of Secrets"] == 1          # front face only, as Forge names it
    assert d.main["Island"] == 40
    assert d.size == 42


def test_parse_arena_old_style_sideboard():
    d = D.parse_arena(STANDARD_TEXT)
    assert d.main == {"Lightning Strike": 4, "Mountain": 20, "Opt": 2}
    assert d.side == {"Abrade": 2}


def test_dck_round_trip(tmp_path):
    d = D.parse_arena(ARENA_TEXT, "Zimone")
    p = d.save(tmp_path / "z.dck")
    back = D.read_dck(p)
    assert back.name == "Zimone"
    assert back.commanders == d.commanders
    assert back.main == d.main
    assert D.parse_arena(d.to_arena()).main == d.main


def test_check_rules():
    d = D.parse_arena(ARENA_TEXT)
    probs = D.check(d, formats.get("brawl"), known_names={"Sol Ring", "Island"})
    assert any("99" in p for p in probs)
    assert any("Delver of Secrets" in p and "Forge" in p for p in probs)
    s = D.parse_arena("5 Opt\n55 Island")
    assert any("four copies" in p for p in D.check(s, formats.get("standard")))
    assert not D.check(D.parse_arena("4 Opt\n56 Island"), formats.get("standard"))


def test_formats():
    assert formats.get("Standard Brawl").forge == "brawl"
    assert formats.get("historic").forge == "constructed"


def test_wilson_and_compare():
    lo, hi = stats.wilson(50, 100)
    assert 0.40 < lo < 0.41 and 0.59 < hi < 0.60
    a = [{"result": "Win"}] * 600 + [{"result": "Loss"}] * 400
    b = [{"result": "Win"}] * 500 + [{"result": "Loss"}] * 500
    c = stats.compare(a, b)
    assert abs(c["diff"] - 0.1) < 1e-9 and c["p_value"] < 0.001
    assert stats.games_needed(0.03) > 2000


def test_draws_count_half():
    s = stats.summary([{"result": "Win"}, {"result": "Draw"}, {"result": "Error"}])
    assert s["games"] == 2 and s["win_rate"] == 0.75 and s["errors"] == 1


def test_plan_spreads_games_evenly():
    jobs = runner.plan(["a", "b", "c"], 65, batch=10)
    assert sum(n for _, n in jobs) == 65
    per = {o: sum(n for x, n in jobs if x == o) for o in "abc"}
    assert max(per.values()) - min(per.values()) <= 1
    assert [o for o, _ in jobs[:3]] == ["a", "b", "c"]   # interleaved


def test_log_reader():
    lines = (Path(__file__).parent / "fixtures" / "player_log_sample.txt").read_text().splitlines()
    r = arena_log.LogReader()
    for l in lines:
        r.feed(l)
    assert len(r.decks) == 1
    deck = next(iter(r.decks.values()))
    assert deck.name == "My Deck" and deck.cards.count(111) == 2 and deck.commanders == [999]
    m = r.matches["m-1"]
    assert m.my_seat == "1" and m.result == "Win"
    assert m.opp_seen[555] == 1 and 777 in m.opp_commanders
    assert 111 not in m.opp_seen
