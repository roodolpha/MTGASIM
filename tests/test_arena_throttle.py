"""Sims back off while MTG Arena is open (runner.while_arena)."""
import threading
import time

from brewbench import runner


class Cfg(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class FakeRun(runner.Run):
    def __init__(self, mode):   # skip the real set-up: only _wait_for_turn is under test
        self.cfg, self.stopping = Cfg(while_arena=mode), False


def _arena(open_):
    runner._ARENA.update(open=open_, checked=time.time() + 3600)


def test_full_ignores_arena():
    _arena(True)
    runner._ACTIVE.update(n=3, waiting=0)
    try:
        assert FakeRun("full")._wait_for_turn()
        assert runner._ACTIVE["n"] == 4
    finally:
        runner._ACTIVE.update(n=0, waiting=0)


def test_slow_allows_one_then_holds(monkeypatch):
    _arena(True)
    monkeypatch.setattr(runner, "ARENA_POLL", 0.05)
    runner._ACTIVE.update(n=0, waiting=0)
    r = FakeRun("slow")
    assert r._wait_for_turn()            # the first batch may run
    got = []
    t = threading.Thread(target=lambda: got.append(r._wait_for_turn()))
    t.start()
    time.sleep(0.3)
    assert not got and runner._ACTIVE["waiting"] == 1   # the second waits
    assert runner.load_state(r.cfg)["held"]
    _arena(False)                        # Arena closed: it goes
    t.join(2)
    assert got == [True] and runner._ACTIVE["n"] == 2 and runner._ACTIVE["waiting"] == 0
    runner._ACTIVE.update(n=0, waiting=0)


def test_pause_holds_until_stop(monkeypatch):
    _arena(True)
    monkeypatch.setattr(runner, "ARENA_POLL", 0.05)
    runner._ACTIVE.update(n=0, waiting=0)
    r = FakeRun("pause")
    got = []
    t = threading.Thread(target=lambda: got.append(r._wait_for_turn()))
    t.start()
    time.sleep(0.3)
    assert not got
    r.stopping = True                    # Stop while held: the batch never starts
    t.join(2)
    assert got == [False] and runner._ACTIVE == {"n": 0, "waiting": 0}
    _arena(False)


def test_unknown_mode_is_slow():
    assert runner.while_arena(Cfg(while_arena="turbo")) == "slow"
    assert runner.while_arena(Cfg()) == "slow"
