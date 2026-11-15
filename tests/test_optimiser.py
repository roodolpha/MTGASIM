import random

from mtgasim import decks as D, formats, optimiser, stats
from mtgasim.config import Config


def fake_games(deck, opps, games, seed):
    """Seeded fake games: each game has a base chance; 'Good Card' adds 15 points, 'Bad Card' costs 10.
    Same seed -> same random draws, so paired tests behave like the real seeded harness."""
    rng = random.Random(seed)
    out = []
    bonus = 0.15 * deck.main.get("Good Card", 0) - 0.10 * deck.main.get("Bad Card", 0)
    for i in range(games):
        u = rng.random()
        p = 0.5 + bonus
        res = "Win" if u < p else "Loss"
        perms = [["Bad Card", 1, 1, 0, 0, 0]] if deck.main.get("Bad Card") and i % 2 else []
        out.append({"result": res, "pair": f"{opps[i % len(opps)]}:{i}", "first": "a", "turns": 10,
                    "states": [{"t": 3, "a": {"perms": perms}, "b": {"perms": []}}]})
    return out


def test_paired_stats():
    a = [{"result": "Win", "pair": str(i)} for i in range(100)]
    b = [{"result": "Win" if i % 4 else "Loss", "pair": str(i)} for i in range(100)]
    r = stats.paired(a, b)
    assert r["n"] == 100 and abs(r["diff"] - 0.25) < 1e-9 and r["p_value"] < 0.001


def test_split_is_stable():
    opps = [f"deck{i}.dck" for i in range(20)]
    t1, h1 = optimiser.split_gauntlet(opps)
    t2, h2 = optimiser.split_gauntlet(list(reversed(opps)))
    assert h1 == h2 and set(t1) | set(h1) == set(opps) and not set(t1) & set(h1)


def test_optimiser_keeps_the_good_swap(tmp_path, monkeypatch):
    cfg = Config(tmp_path)
    deck = D.parse_arena("Deck\n4 Bad Card\n4 Filler\n52 Island", "Test")
    path = deck.save(cfg.decks_dir / "test.dck")
    opps = [f"opp{i}.dck" for i in range(10)]
    opt = optimiser.Optimiser(cfg, formats.get("standard"), path, opps, ["Good Card", "Meh Card"],
                              log=lambda *_: None, screen=300, confirm=800, holdout=400)
    monkeypatch.setattr(opt, "_run", lambda d, o, n, seed, tag: fake_games(d, o, n, seed))
    report = opt.run(max_tests=6)
    acc = opt.state["accepted"]
    assert acc and acc[0]["in"] == "Good Card" and acc[0]["out"] == "Bad Card"
    # swapping Filler for Meh Card changes nothing, so it must never be kept (Meh for Bad is a real gain)
    assert all(r["out"] == "Bad Card" for r in acc)
    assert "Good Card" in opt.deck.main
    assert "accepted" in report
    # resuming picks up the saved state instead of starting over
    again = optimiser.Optimiser(cfg, formats.get("standard"), path, opps, ["Good Card"], log=lambda *_: None)
    assert again.state["accepted"] == acc
