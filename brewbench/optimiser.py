"""Deck optimiser: tests one-card swaps against your gauntlet and keeps the ones that really help.

Every test is paired: the deck and the variant play the same seeded games (same shuffles, same opponents),
so a swap only has to beat noise from the games where the swapped card actually mattered.

For each swap (cut X, add Y):
  1. screen   - a short paired run; drop it unless it's ahead
  2. confirm  - a longer paired run on fresh seeds; keep only if z >= 1.64 (about 95% one-sided)
  3. hold-out - a paired run against opponent decks it was never tuned on; drop it if it's worse there
Accepted swaps become the new deck and the search carries on from it. State is saved after every step,
so stopping and running the command again resumes where it left off.
"""
import hashlib
import json
import time
from pathlib import Path

from . import decks as D, runner, stats

SCREEN_GAMES = 200
CONFIRM_GAMES = 800
HOLDOUT_GAMES = 400
Z_ACCEPT = 1.64
HOLDOUT_TOLERANCE = -0.02   # the hold-out may be up to 2 points worse before we call it overfitting
HOLDOUT_SHARE = 0.2


def split_gauntlet(opponents, share=HOLDOUT_SHARE):
    """Stable split by file name hash, so the same decks are held out every time."""
    opps = sorted(opponents, key=lambda p: Path(p).name)
    if len(opps) < 5:
        return opps, opps   # too few to hold any out: the hold-out check then just re-tests on fresh seeds
    hold = [o for o in opps if int(hashlib.sha1(Path(o).name.encode()).hexdigest(), 16) % 100 < share * 100]
    if not hold:
        hold = opps[-1:]
    train = [o for o in opps if o not in hold]
    return train, hold


def deck_hash(deck):
    body = "|".join(sorted(deck.commanders)) + "#" + "|".join(f"{q} {n}" for n, q in sorted(deck.main.items()))
    return hashlib.sha1(body.encode()).hexdigest()[:10]


class Stopped(Exception):
    """Raised inside a run when stop() is called; run() catches it and saves."""


class Optimiser:
    def __init__(self, cfg, fmt, deck_path, opponents, pool, outs=None, protect=(), instances=None, log=print,
                 screen=SCREEN_GAMES, confirm=CONFIRM_GAMES, holdout=HOLDOUT_GAMES):
        self.cfg, self.fmt, self.log = cfg, fmt, log
        self.start_deck = D.load(deck_path)
        self.slug = Path(deck_path).stem
        self.dir = cfg.home / "optimiser" / self.slug
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "state.json"
        self.train, self.hold = split_gauntlet(opponents)
        self.pool = [D.clean_name(p) for p in pool]
        self.forced_outs = [D.clean_name(o) for o in (outs or [])]
        self.protect = set(D.clean_name(p) for p in protect) | set(D.BASICS)
        self.instances = instances
        self.n = {"screen": screen, "confirm": confirm, "holdout": holdout}
        self.state = self._load()
        self.stopping = False
        self._current = None     # the Run in progress, so stop() can end it

    # ---------------------------------------------------------------- state
    def _load(self):
        if self.state_file.exists():
            st = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.log(f"Resuming: {len(st['accepted'])} swap(s) accepted, {len(st['tried'])} tried so far")
            return st
        return {"started": int(time.time()), "deck": self.start_deck.to_arena(), "accepted": [], "tried": {},
                "baselines": {}, "seed_base": 10_000}

    def _save(self):
        self.state_file.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    @property
    def deck(self):
        return D.parse_arena(self.state["deck"], self.slug)

    # ---------------------------------------------------------------- running
    def _run(self, deck, opps, games, seed, tag):
        path = deck.save(self.dir / "variants" / f"{deck_hash(deck)}.dck")
        r = runner.Run(self.cfg, self.fmt, path, opps, games, self.instances, seed, f"{self.slug}:{tag}",
                       out_dir=self.dir / "runs", log=lambda *_: None)
        self._current = r
        try:
            games_ = r.start()
        finally:
            self._current = None
        if self.stopping:
            raise Stopped()
        return games_

    def stop(self):
        """Ends the test in progress; everything finished so far is saved, and running again resumes."""
        self.stopping = True
        r = self._current
        if r is not None:
            r.stop()

    def _baseline(self, stage, opps, games, seed):
        """The current deck's games for one (stage, seed): cached, because every swap compares against it."""
        key = f"{deck_hash(self.deck)}:{stage}:{seed}"
        cache = self.dir / "baselines" / f"{key.replace(':', '_')}.json"
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        games_ = self._run(self.deck, opps, games, seed, f"base-{stage}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(games_), encoding="utf-8")
        return games_

    def _stage(self, variant, stage, opps, seed):
        base = self._baseline(stage, opps, self.n[stage], seed)
        var = self._run(variant, opps, self.n[stage], seed, stage)
        return stats.paired(var, base), base

    # ---------------------------------------------------------------- choosing swaps
    def cut_candidates(self, base_games):
        """Cards to try cutting: the ones you name first, then permanents whose presence on the battlefield
        goes with the lowest win rate in the baseline games (a hint, not proof: that's what the test is for)."""
        deck = self.deck
        mine = [n for n in deck.main if n not in self.protect and n not in deck.commanders]
        outs = [o for o in self.forced_outs if o in deck.main]
        pres = stats.card_presence(base_games)
        ranked = sorted((n for n in mine if n in pres and pres[n]["games_seen"] >= 10), key=lambda n: pres[n]["delta"])
        for n in ranked:
            if n not in outs:
                outs.append(n)
        return outs

    def swaps(self, base_games, per_out=4):
        deck = self.deck
        ins = [p for p in self.pool if p not in deck.main and p not in deck.commanders]
        for out in self.cut_candidates(base_games):
            k = 0
            for add in ins:
                key = f"-{out}|+{add}|{deck_hash(deck)}"
                if key in self.state["tried"]:
                    continue
                yield out, add, key
                k += 1
                if k >= per_out:
                    break

    # ---------------------------------------------------------------- the loop
    def run(self, max_tests=None, until=None):
        try:
            return self._loop(max_tests, until)
        except Stopped:
            self.log("Stopped. Run it again to carry on from here.")
            return self.report()

    def _loop(self, max_tests=None, until=None):
        tests = 0
        while True:
            seed0 = self.state["seed_base"] + 100 * len(self.state["accepted"])
            base_screen = self._baseline("screen", self.train, self.n["screen"], seed0)
            s0 = stats.summary(base_screen)
            self.log(f"Current deck: {100 * s0['win_rate']:.1f}% over {s0['games']} screening games")
            progressed = False
            for out, add, key in self.swaps(base_screen):
                if (max_tests and tests >= max_tests) or (until and time.time() > until):
                    self.log("Stopping here; run again to carry on.")
                    return self.report()
                tests += 1
                variant = self.deck
                variant.main[out] -= 1
                if variant.main[out] <= 0:
                    del variant.main[out]
                variant.main[add] += 1
                rec = {"out": out, "in": add, "ts": int(time.time())}
                self.log(f"Testing -{out} +{add}")
                res, _ = self._stage(variant, "screen", self.train, seed0)
                rec["screen"] = res
                ok = res["diff"] is not None and res["diff"] > 0
                if ok:
                    res, _ = self._stage(variant, "confirm", self.train, seed0 + 1)
                    rec["confirm"] = res
                    ok = res["z"] is not None and res["z"] >= Z_ACCEPT
                if ok:
                    res, _ = self._stage(variant, "holdout", self.hold, seed0 + 2)
                    rec["holdout"] = res
                    ok = res["diff"] is not None and res["diff"] >= HOLDOUT_TOLERANCE
                rec["accepted"] = bool(ok)
                self.state["tried"][key] = rec
                stage = "holdout" if "holdout" in rec else "confirm" if "confirm" in rec else "screen"
                d = rec[stage]["diff"]
                self.log(f"  {'ACCEPTED' if ok else 'rejected'} at {stage}"
                         + (f" ({100 * d:+.1f} points)" if d is not None else ""))
                if ok:
                    self.state["accepted"].append(rec)
                    self.state["deck"] = variant.to_arena()
                    self._save()
                    progressed = True
                    break   # re-baseline on the new deck
                self._save()
            if not progressed:
                self.log("No more swaps to try with this pool.")
                return self.report()

    def report(self):
        acc = self.state["accepted"]
        lines = [f"{len(acc)} swap(s) accepted out of {len(self.state['tried'])} tested:"]
        f = lambda v, fmt: "?" if v is None else format(v, fmt)
        for r in acc:
            c, h = r.get("confirm") or {}, r.get("holdout") or {}
            lines.append(f"  -{r['out']} +{r['in']}   confirm {f(c.get('diff') and 100 * c['diff'], '+.1f')} pts "
                         f"(z {f(c.get('z'), '.2f')}), hold-out {f(h.get('diff') and 100 * h['diff'], '+.1f')} pts")
        out = self.dir / "optimised.txt"
        out.write_text(self.state["deck"], encoding="utf-8")
        lines.append(f"Current list (Arena import format): {out}")
        return "\n".join(lines)
