"""A real Arena game (names scrubbed), run through both log readers. If an Arena update changes the log format,
these are the tests that break first."""
import gzip
import importlib
import os
from pathlib import Path

from mtgasim import arena_log

FIXTURE = Path(__file__).parent / "fixtures" / "real_match.log.gz"


def lines():
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return f.read().splitlines()


def test_simple_reader_finds_the_game():
    r = arena_log.LogReader()
    for l in lines():
        r.feed(l)
    assert len(r.matches) == 1
    m = next(iter(r.matches.values()))
    assert m.result in ("Win", "Loss", "Draw")
    assert m.my_seat in ("1", "2")
    assert len(m.my_deck) >= 59          # the deck Arena sent at the start
    assert m.opp_seen                    # we saw some of their cards
    assert m.event


def test_tracker_records_the_full_game(tmp_path):
    os.environ["MTGASIM_TRACKER_DIR"] = str(tmp_path)
    import mtgasim.tracker_engine as E
    E = importlib.reload(E)
    store = {}
    p = E.MatchParser(store, {})
    for l in lines():
        p.feed(l)
    assert len(store) == 1
    m = next(iter(store.values()))
    assert m["result"] in ("Win", "Loss", "Draw")
    assert m["turns"] >= 3
    assert m["timeline"] and m["board"]
    assert any(x["side"] == "me" for x in m["plays"]) and any(x["side"] == "opp" for x in m["plays"])
    assert m["my_name"] in ("Player1", "Player2")      # names in the fixture are scrubbed
    assert m["kept"] is not None
