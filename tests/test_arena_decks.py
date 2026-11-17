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


def test_share_reads_tracker_history():
    from brewbench import share
    m = share._from_tracker({"match_id": "abc", "start": "1793830402324", "event": "Brawl_Ladder", "result": "Loss",
                             "my_commanders": "[93839]", "opp_commanders": [96873], "opp_seen": [1, 2, 2],
                             "deck": {"cards": [5, 6, 6]}})
    assert m.match_id == "abc" and m.start == 1793830402324 and m.my_commanders == [93839]
    assert m.opp_commanders == {96873} and m.opp_seen[2] == 2 and m.my_deck == [5, 6, 6]
    assert share._from_tracker({"result": "Win"}) is None


def test_sim_process_matching():
    from brewbench import runner
    assert runner._is_sim(r'"C:\jre\bin\java.exe" -Xmx2g -cp a.jar;b.jar brewbench.Sim brawl x.dck y.dck 10 o.jsonl')
    assert not runner._is_sim("notepad brewbench.Sim.txt")
    assert runner._is_driver('"C:\\Python\\python.exe" -m brewbench run Zimone -f brawl -n 500')
    assert runner._is_driver("brewbench-cli.exe optimise Zimone -f brawl")
    assert not runner._is_driver("py -3 -m brewbench serve")
    assert not runner._is_driver('"C:\\Programs\\brewbench\\brewbench.exe" --background')


def test_site_latest_json_matches_this_version():
    """Bump site/latest.json with every release, or installed apps won't hear about it."""
    import json, pathlib
    from brewbench import __version__
    info = json.loads((pathlib.Path(__file__).parent.parent / "site" / "latest.json").read_text())
    assert info["version"] == __version__ and info["url"].endswith(".exe")


def test_update_check_compares_versions(tmp_path):
    from brewbench import updates
    f = tmp_path / "latest.json"
    f.write_text('{"version": "99.0.0", "url": "https://x/setup.exe"}')
    info = updates.check(force=True, url=f.as_uri())
    assert info["newer"] and info["latest"] == "99.0.0" and not info["can_install"]
    f.write_text('{"version": "0.0.1", "url": "https://x/setup.exe"}')
    assert not updates.check(force=True, url=f.as_uri())["newer"]
    assert updates.vtuple("v0.10.0") > updates.vtuple("0.9.9")


def test_build_faced_makes_one_deck_per_new_commander(tmp_path, monkeypatch):
    from collections import Counter
    from brewbench import formats, gauntlet
    cfg = Config(tmp_path / "home")
    fmt = formats.get("brawl")
    monkeypatch.setattr(gauntlet, "faced_commanders", lambda cfg, k: {
        "Tam, the Possibility": (5, Counter({"Opt": 2})), "Unknown Guy": (2, Counter()), "Kaalia": (1, Counter())})
    def fake(c, seen, names, size=99, use_edhrec=True):
        d = D.Deck(name=c, commanders=[c]); d.main["Island"] = size; return d
    monkeypatch.setattr(gauntlet, "brawl_deck", fake)
    (cfg.gauntlet_dir("brawl")).mkdir(parents=True, exist_ok=True)
    D.Deck(name="Kaalia", commanders=["Kaalia"], main=Counter({"Plains": 99})).save(cfg.gauntlet_dir("brawl") / "kaalia.dck")
    made, skipped = gauntlet.build_faced(cfg, fmt, {"Tam, the Possibility", "Kaalia"})
    assert made == ["Tam, the Possibility"]                      # Kaalia already there
    assert skipped and "Unknown Guy" in skipped[0]               # not in Forge
    assert [d["commander"] for d in gauntlet.describe(cfg.gauntlet_dir("brawl"))] == ["Kaalia", "Tam, the Possibility"]


def test_run_retries_games_that_did_not_finish(tmp_path, monkeypatch):
    """A batch that produces no games (busy PC, Java didn't start) is retried once; if it still fails the run
    reports how many games are missing instead of quietly calling itself finished."""
    import sys, textwrap
    from brewbench import formats, runner
    fake = tmp_path / "fakeforge.py"
    fake.write_text(textwrap.dedent('''
        import json, sys, os
        n, out, flag = int(sys.argv[1]), sys.argv[2], sys.argv[3]
        marker = os.path.join(os.path.dirname(out), "flaky.tried")
        if flag == "flaky" and not os.path.exists(marker):
            open(marker, "w").close(); sys.exit(1)               # first attempt: dies before playing
        if flag == "dead":
            sys.exit(1)
        with open(out, "w") as f:
            for i in range(n):
                f.write(json.dumps({"result": "Win", "turns": 9}) + "\\n"); print("GAME_DONE", flush=True)
    '''))
    def cmd(java, forge_dir, fmt, deck, opp, n, out, timeout, seed):
        flag = "flaky" if "flaky" in str(opp) else "dead" if "dead" in str(opp) else "ok"
        return [sys.executable, str(fake), str(n), str(out).replace(".part", "") + ".part", flag]
    monkeypatch.setattr(runner.forge, "command", cmd)
    cfg = Config(tmp_path / "home")
    for name in ("flaky", "dead", "mine"):
        (tmp_path / f"{name}.dck").write_text("[Main]\n60 Island\n")
    r = runner.Run(cfg, formats.get("standard"), tmp_path / "mine.dck", [tmp_path / "flaky.dck", tmp_path / "dead.dck"],
                   4, instances=1, out_dir=tmp_path / "res", log=lambda *a: None)
    games = []
    for opp, n in runner.plan(r.opponents, r.games):
        games += r._batch(sys.executable, tmp_path, opp, n, len(games))
    assert sum(1 for g in games if "flaky" in g["pair"]) == 2      # recovered on the retry
    assert r.missing == 2 and "dead" in r.problems[0]             # reported, not hidden


def test_download_meta_saves_and_replaces(tmp_path, monkeypatch):
    from brewbench import formats, gauntlet
    cfg = Config(tmp_path / "home")
    fmt = formats.get("standard")
    lists = [{"name": "Mono-Red Aggro", "hash": "a1", "list": "Deck\n20 Mountain\n40 Shock"},
             {"name": "Tiny", "hash": "b2", "list": "Deck\n4 Opt"}]
    monkeypatch.setattr(gauntlet, "_get", lambda url, timeout=30: {"decks": lists})
    folder = cfg.gauntlet_dir("standard"); folder.mkdir(parents=True)
    (folder / "meta-old.dck").write_text("[Main]\n60 Island\n")
    (folder / "mine.dck").write_text("[Main]\n60 Island\n")
    assert gauntlet.download_meta(cfg, fmt, api="https://x") == ["Mono-Red Aggro"]   # too-small list skipped
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["meta-mono-red-aggro.dck", "mine.dck"]                         # old meta replaced, yours kept


def test_swap_verdict_and_changes():
    from collections import Counter
    from brewbench import server
    a = D.Deck(name="A", commanders=["Zimone"], main=Counter({"Opt": 1, "Island": 98}))
    b = D.Deck(name="B", commanders=["Zimone"], main=Counter({"Ponder": 1, "Island": 98}))
    assert server.deck_changes(a, b) == ([("Opt", 1)], [("Ponder", 1)])
    better = server.swap_verdict({"n": 400, "diff": -0.06, "z": -3.0, "p_value": 0.998}, 400)
    assert better["kind"] == "better" and "+6.0" in better["text"]
    worse = server.swap_verdict({"n": 400, "diff": 0.06, "z": 3.0, "p_value": 0.002}, 400)
    assert worse["kind"] == "worse"
    unclear = server.swap_verdict({"n": 400, "diff": -0.01, "z": -0.5, "p_value": 0.69}, 400)
    assert unclear["kind"] == "unclear" and unclear["more"] > 0
    assert server.swap_verdict({"n": 1, "diff": None, "z": None, "p_value": None}, 1)["kind"] == "none"


def test_plan_weights_games_by_how_often_faced():
    from brewbench import runner
    opps = ["a", "b", "c"]
    per = lambda jobs: {o: sum(n for x, n in jobs if x == o) for o in opps}
    assert per(runner.plan(opps, 30)) == {"a": 10, "b": 10, "c": 10}
    w = per(runner.plan(opps, 30, weights=[6, 3, 0]))
    assert sum(w.values()) == 30 and w["c"] == 1 and w["a"] > w["b"] > w["c"]   # never-faced still gets a game
    assert per(runner.plan(opps, 30, weights=[0, 0, 0])) == {"a": 10, "b": 10, "c": 10}


def test_optimiser_stop_saves_and_returns(tmp_path, monkeypatch):
    from brewbench import formats, optimiser as O
    cfg = Config(tmp_path / "home")
    deck = tmp_path / "me.dck"; deck.write_text("[Main]\n4 Opt\n56 Island\n")
    opp = tmp_path / "o.dck"; opp.write_text("[Main]\n60 Island\n")
    o = O.Optimiser(cfg, formats.get("standard"), deck, [opp], ["Ponder"], log=lambda *a: None)
    class R:
        def __init__(self, *a, **k): self.stopped = False
        def start(self): o.stop(); return []        # stop arrives during the first test
        def stop(self): self.stopped = True
    monkeypatch.setattr(O.runner, "Run", R)
    report = o.run()
    assert o.stopping and "accepted" in report


def test_crash_reports_are_opt_in_and_scrubbed(tmp_path, monkeypatch):
    from brewbench import crash
    cfg = Config(tmp_path / "home")
    sent = []
    monkeypatch.setattr(crash.threading, "Thread", lambda target, **k: type("T", (), {"start": lambda self: sent.append(1)})())
    try:
        raise ValueError(r"can't open C:\Users\roodo\.mtgasim\decks\x.dck")
    except ValueError as e:
        err = e
    assert crash.report(err, "test", cfg) is False and not sent          # off by default: nothing sent
    cfg.set("crash_reports", True)
    assert crash.report(err, "test", cfg) is True and sent
    assert crash.report(err, "test", cfg) is False                        # same problem again: not resent
    s = crash.scrub(r"C:\Users\roodo\.mtgasim and /home/alice/x and /Users/bob/y")
    assert "roodo" not in s and "alice" not in s and "bob" not in s


def test_card_database_found_from_arena_log(tmp_path):
    """Arena installed anywhere: the log's Mono path line says where, so names come from Arena's own database."""
    from brewbench import cards
    data = tmp_path / "Games" / "Odd Place" / "MTGA" / "MTGA_Data"
    raw = data / "Downloads" / "Raw"
    raw.mkdir(parents=True)
    db = raw / "Raw_CardDatabase_abc.mtga"
    db.write_bytes(b"")
    log = tmp_path / "Player.log"
    log.write_text("Mono path[0] = '" + str(data / "Managed").replace("\\", "/") + "'\nInitialize engine version: 6000\n")
    assert cards.install_dirs_from_log([log]) == [str(data)]
    assert cards._arena_db_candidates([log]) == [str(db)]


def test_card_ideas_from_edhrec(tmp_path, monkeypatch):
    """Ideas leave out cards already in the deck, basics and cards not legal on Arena, sorted by how many decks play them."""
    from brewbench import config, decks as D, ideas, formats, cards as C
    cfg = config.Config(tmp_path)
    page = {"container": {"json_dict": {"cardlists": [
        {"tag": "topcards", "header": "Top Cards", "cardviews": [
            {"name": "Simic Ascendancy", "num_decks": 50, "potential_decks": 100, "synergy": 0.4}]},
        {"tag": "creatures", "header": "Creatures", "cardviews": [
            {"name": "Llanowar Elves", "num_decks": 80, "potential_decks": 100, "synergy": 0.0},
            {"name": "Birds of Paradise", "num_decks": 90, "potential_decks": 100, "synergy": 0.1}]},
        {"tag": "lands", "header": "Lands", "cardviews": [
            {"name": "Forest", "num_decks": 99, "potential_decks": 100, "synergy": 0.0},
            {"name": "Sol Ring", "num_decks": 95, "potential_decks": 100, "synergy": 0.0}]}]}}}
    monkeypatch.setattr(ideas, "_page", lambda cfg, c: page)
    monkeypatch.setattr(C, "legality", lambda names, k, f=None: {n: ("not_legal" if n == "Sol Ring" else "legal") for n in names})
    monkeypatch.setattr(C, "identity", lambda names, f=None: {"Simic Ascendancy": {"type": "Enchantment"}, "Birds of Paradise": {"type": "Creature — Bird"}})
    deck = D.Deck(name="Z", format="brawl")
    deck.commanders.append("Zimone, Paradox Sculptor")
    deck.main["Llanowar Elves"] += 1
    r = ideas.for_deck(cfg, deck, formats.get("brawl"))
    assert [c["name"] for c in r["cards"]] == ["Birds of Paradise", "Simic Ascendancy"]
    assert r["cards"][1]["category"] == "Enchantment" and r["cards"][1]["tags"] == ["top"]
    assert r["left_out"] == 1 and r["decks"] == 100


def test_run_matchups_show_commander_names(tmp_path):
    """A run's matchups name the opponent's commander, not the deck file's slug."""
    import json
    from brewbench import config, server
    cfg = config.Config(tmp_path)
    g = cfg.gauntlet_dir("brawl"); g.mkdir(parents=True, exist_ok=True)
    (g / "aerith-gainsborough.dck").write_text("[metadata]\nName=Aerith Gainsborough\n[Commander]\n1 Aerith Gainsborough\n[Main]\n1 Plains\n")
    rd = cfg.results_dir; rd.mkdir(parents=True, exist_ok=True)
    (rd / "r1.meta.json").write_text(json.dumps({"run": "r1", "format": "brawl", "opponents": ["/elsewhere/aerith-gainsborough.dck"]}))
    rows = [{"result": r, "first": "a", "turns": 10, "deck_b": d} for r, d in
            [("Win", "aerith-gainsborough.dck"), ("Loss", "aerith-gainsborough.dck"), ("Win", "doctor-doom-king-of-latveria.dck")]]
    (rd / "r1.jsonl").write_text("\n".join(json.dumps(x) for x in rows))
    out = {o["id"]: o for o in server.run_detail(cfg, "r1")["opponents"]}
    assert out["aerith-gainsborough"]["opponent"] == "Aerith Gainsborough"
    assert out["aerith-gainsborough"]["commander"] == "Aerith Gainsborough"
    assert out["doctor-doom-king-of-latveria"]["opponent"] == "Doctor Doom King of Latveria"   # no deck file: tidied slug


def test_share_sends_only_new_or_changed_rows(tmp_path, monkeypatch):
    """Each share sends what the site doesn't have yet: a re-share with nothing new sends nothing."""
    from brewbench import config, share
    cfg = config.Config(tmp_path)
    cfg.data.update(share_id="c1", share_key="k", share_sent_name=None, share_sent_public=False)
    payload = {"matches": [{"match_key": "a", "result": "Win"}],
               "sims": [{"run_id": "r", "opp_key": "o", "games": 10, "wins": 5}], "decks": []}
    monkeypatch.setattr(share, "build_payload", lambda cfg, lists=False: payload)
    sent = []
    monkeypatch.setattr(share.Client, "upload", lambda self, p: sent.append(p) or {"matches": len(p["matches"]), "sims": len(p["sims"]), "decks": 0, "rejected": 0})
    share.share_now(cfg)
    assert len(sent[0]["matches"]) == 1 and len(sent[0]["sims"]) == 1
    share.share_now(cfg)
    assert len(sent) == 1                                   # nothing new: no upload at all
    payload["sims"][0]["games"] = 20                        # a sim run that kept going
    payload["matches"].append({"match_key": "b", "result": "Loss"})
    share.share_now(cfg)
    assert sent[1]["sims"][0]["games"] == 20 and [m["match_key"] for m in sent[1]["matches"]] == ["b"]


def test_one_start_up_plays_several_opponents(tmp_path, monkeypatch):
    """Short runs against a big gauntlet pack several opponents into one Java start-up (starting Forge is the
    slow part). Games are credited to the right opponent, and only the missing ones are retried."""
    import sys, textwrap
    from brewbench import formats, runner
    jobs = runner.pack(runner.plan(["a", "b", "c", "d", "e"], 25, batch=10), 10)
    assert [sum(n for _, n in j) for j in jobs] == [10, 10, 5]
    assert {o: sum(n for j in jobs for x, n in j if x == o) for o in "abcde"} == dict.fromkeys("abcde", 5)
    assert runner.batch_size(200, 16) == 13 and runner.batch_size(2500, 16) == 20 and runner.batch_size(3, 16) == 3
    fake = tmp_path / "fakeforge.py"
    fake.write_text(textwrap.dedent('''
        import json, sys, os
        target, out, games = sys.argv[1], sys.argv[2], sys.argv[3]
        opps = [l.split("\\t") for l in open(target[1:]).read().splitlines()] if target.startswith("@") else [[target, games]]
        marker = os.path.join(os.path.dirname(out), "flaky.tried")
        with open(out, "w") as f:
            for slot, (path, n) in enumerate(opps):
                for i in range(int(n)):
                    if "flaky" in path and i == 1 and not os.path.exists(marker):
                        open(marker, "w").close(); sys.exit(1)       # dies part-way through the second opponent
                    f.write(json.dumps({"result": "Win", "deck_b": os.path.basename(path), "slot": slot}) + "\\n")
                    f.flush(); print("GAME_DONE", flush=True)
    '''))
    calls = []
    def cmd(java, forge_dir, fmt, deck, opp, n, out, timeout, seed):
        calls.append(str(opp))
        return [sys.executable, str(fake), str(opp), str(out), str(n)]
    monkeypatch.setattr(runner.forge, "command", cmd)
    cfg = Config(tmp_path / "home")
    for name in ("ok", "flaky", "mine"):
        (tmp_path / f"{name}.dck").write_text("[Main]\n60 Island\n")
    r = runner.Run(cfg, formats.get("standard"), tmp_path / "mine.dck", [], 0, instances=1,
                   out_dir=tmp_path / "res", log=lambda *a: None)
    games = r._batch(sys.executable, tmp_path, [(tmp_path / "ok.dck", 3), (tmp_path / "flaky.dck", 3)], 0, 0)
    assert calls[0].startswith("@") and len(calls) == 2              # one start-up for both, then one retry
    per = {}
    for g in games:
        per[g["deck_b"]] = per.get(g["deck_b"], 0) + 1
        assert "slot" not in g and g["pair"].startswith(g["deck_b"])
    assert per == {"ok.dck": 3, "flaky.dck": 3} and r.missing == 0
    assert not list((tmp_path / "res").glob(".*.opps"))
