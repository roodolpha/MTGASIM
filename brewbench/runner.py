"""Runs many Forge games in parallel: your deck against a gauntlet of opponent decks.

Work is split into batches: one Java process plays up to BATCH games, against one or several opponents,
because starting Forge costs several seconds. Games are spread evenly over the gauntlet, so every opponent
gets close to the same number of games."""
import json
import math
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import forge

BATCH = 20            # most games per Java start-up
MIN_BATCH = 5         # fewest, unless the run itself is smaller
GAME_TIMEOUT = 180    # seconds before a stuck game counts as a draw
WAIT_POLL = 2         # seconds between a queued test's checks for its turn
WAITING_FRESH = 5     # seconds a queued test's "I'm next" mark counts for (more than WAIT_POLL)
SETTLED = 20          # seconds a Java process must have run before its death can count as "closed outside"
CLOSE_WINDOW = 6      # seconds: this many Java processes failing this close together means they were closed
ARENA_CHECK = 5       # seconds between checks for MTG Arena being open
ARENA_POLL = 3        # seconds a batch waits before checking again whether it may start
WHILE_ARENA = ("slow", "pause", "full")   # what sims do while Arena is open (setting "while_arena")


# ---- being polite while Arena is open -------------------------------------------------------------------
# Sims are CPU-heavy. While you're playing Arena they shouldn't slow the game down, so new batches either
# wait until only one is running ("slow", the default), wait until Arena closes ("pause"), or ignore it
# ("full"). Batches already running finish normally; each is only a few minutes of games.
_ARENA = {"open": False, "checked": 0.0}
_ACTIVE = {"n": 0, "waiting": 0}   # batches running now / held back by Arena
_ACTIVE_LOCK = threading.Lock()


def _arena_open_now():
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MTGA.exe", "/NH", "/FO", "CSV"],
                               capture_output=True, text=True, timeout=10, creationflags=0x08000000)
            return "mtga.exe" in r.stdout.lower()
        r = subprocess.run(["pgrep", "-x", "MTGA"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def arena_open():
    """Is MTG Arena running? Cached for ARENA_CHECK seconds."""
    now = time.time()
    if now - _ARENA["checked"] >= ARENA_CHECK:
        _ARENA.update(open=_arena_open_now(), checked=now)
    return _ARENA["open"]


def while_arena(cfg):
    mode = (cfg.get("while_arena") or "slow") if cfg else "slow"
    return mode if mode in WHILE_ARENA else "slow"


def load_state(cfg=None):
    """What sims are doing to this PC right now, for the app's banner."""
    mode = while_arena(cfg)
    instances = (cfg.get("instances") if cfg else None) or max(1, (os.cpu_count() or 2) // 2)
    busy = _ACTIVE["n"] or _ACTIVE["waiting"]
    arena = arena_open() if busy and mode != "full" else False   # only look for Arena while sims are going
    return {"active": _ACTIVE["n"], "waiting": _ACTIVE["waiting"], "instances": instances,
            "threads": os.cpu_count() or 0, "arena": arena, "while_arena": mode, "held": arena}


def plan(opponents, games, batch=BATCH, weights=None):
    """[(opponent, n_games)] covering `games` games. Even across opponents, or in proportion to `weights`
    (e.g. how often you face each one), with every opponent getting at least one game."""
    if not opponents:
        return []
    per = [0] * len(opponents)
    w = [max(0.0, float(x or 0)) for x in (weights or [])]
    if len(w) == len(opponents) and sum(w) > 0 and games >= len(opponents):
        per = [1] * len(opponents)                       # everyone plays at least once
        left, tot = games - len(opponents), sum(w)
        shares = [left * x / tot for x in w]
        for i, sh in enumerate(shares):
            per[i] += int(sh)
        rest = games - sum(per)                          # hand out the remainder by largest fraction
        for i in sorted(range(len(shares)), key=lambda i: shares[i] - int(shares[i]), reverse=True)[:rest]:
            per[i] += 1
    else:
        for i in range(games):
            per[i % len(opponents)] += 1
    queues = []
    for opp, n in zip(opponents, per):
        q = []
        while n > 0:
            k = min(batch, n)
            q.append((opp, k))
            n -= k
        queues.append(q)
    # interleave (one batch per opponent in turn) so a run stopped early still covers the gauntlet evenly
    out = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


class SimLock:
    """One test at a time on this PC, across the app, the command line and the optimiser: two tests at once
    share the same cores, so both just run at half speed. An OS file lock, so it's released if a process dies."""

    def __init__(self, path):
        self.path = Path(path)
        self.f = None

    def acquire(self):
        """True if we now hold the lock, False if another test does."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.f = f
        return True

    def release(self):
        if self.f is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.f.close()
        self.f = None


def pack(jobs, size):
    """Group plan() output into Java start-ups of `size` games each: [[(opponent, n), ...], ...].
    An opponent's games may be split across two start-ups; the order of plan() is kept."""
    out, cur, room = [], [], size
    for opp, n in jobs:
        while n > 0:
            k = min(n, room)
            if cur and cur[-1][0] == opp:
                cur[-1] = (opp, cur[-1][1] + k)
            else:
                cur.append((opp, k))
            n -= k
            room -= k
            if room == 0:
                out.append(cur)
                cur, room = [], size
    if cur:
        out.append(cur)
    return out


def faced_weights(opponents):
    """How often you've faced each opponent deck (its Weight=), for plan(); None if none are known,
    so the games are spread evenly instead."""
    from . import decks as D
    w = []
    for o in opponents:
        try:
            w.append(D.read_dck(o).weight or 0)
        except OSError:
            w.append(0)
    return w if any(w) else None


def batch_size(games, instances):
    """Games per Java start-up: enough to keep every instance busy, never more than BATCH."""
    return max(1, min(BATCH, games, max(MIN_BATCH, math.ceil(games / max(1, instances)))))


class _Retry:
    """A batch that came up short and should be tried once more."""
    def __init__(self, games, missing):
        self.games, self.missing = games, missing


class Run:
    """One simulation run. Results stream to <out_dir>/<run_id>.jsonl as games finish."""

    def __init__(self, cfg, fmt, deck_path, opponents, games, instances=None, seed=None, label=None,
                 out_dir=None, log=print):
        self.cfg, self.fmt, self.log = cfg, fmt, log
        self.deck = Path(deck_path)
        self.opponents = [Path(o) for o in opponents]
        self.games = games
        self.instances = instances or cfg.get("instances") or max(1, (os.cpu_count() or 2) // 2)
        self.seed = seed
        self.weights = None      # optional: games per opponent in proportion to these (see plan)
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.label = label or self.deck.stem
        self.out_dir = Path(out_dir or cfg.results_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.results = self.out_dir / f"{self.id}.jsonl"
        self.done = 0
        self.lock = threading.Lock()
        self.stopping = False
        self.procs = set()
        self.missing = 0          # games that never got played (Forge failed to start, crashed or timed out)
        self.problems = []        # short reasons, shown to the user
        self._fails = []          # when batches came up short, to tell a mass close-down from a crash

    def _batch(self, java, forge_dir, opp, n, idx, attempt=1):
        """One Java start-up. `opp` is an opponent deck (playing `n` games), or a list of (opponent, games)."""
        segs = [(Path(o), k) for o, k in opp] if isinstance(opp, list) else [(Path(opp), n)]
        segs = [(o, k) for o, k in segs if k > 0]
        n = sum(k for _, k in segs)
        if self.stopping or not segs:   # queued batches after Stop: don't start them
            return []
        tmp = self.out_dir / f".{self.id}-{idx}-{attempt}.part"
        errf = self.out_dir / f".{self.id}-{idx}-{attempt}.err"
        seed = None if self.seed is None else self.seed + idx
        if len(segs) == 1:
            target = segs[0][0].resolve()
        else:
            lst = self.out_dir / f".{self.id}-{idx}-{attempt}.opps"
            lst.write_text("".join(f"{o.resolve()}\t{k}\n" for o, k in segs), encoding="utf-8")
            target = f"@{lst.resolve()}"
        cmd = forge.command(java, forge_dir, self.fmt, self.deck.resolve(), target, n, tmp.resolve(),
                            GAME_TIMEOUT, seed)
        if not self._wait_for_turn():
            return []
        try:
            got = self._launch(cmd, forge_dir, segs, n, tmp, errf, seed, idx, attempt, java)
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE["n"] -= 1
        if isinstance(got, _Retry):
            return got.games + self._batch(java, forge_dir, got.missing, 0, idx + 10000, attempt=2)
        return got

    def _wait_for_turn(self):
        """Holds a batch back while Arena is open (see while_arena). False if Stop was pressed meanwhile."""
        mode = while_arena(self.cfg)
        counted = False
        try:
            while True:
                if self.stopping:
                    return False
                arena = mode != "full" and arena_open()   # outside the lock: the check can take a moment
                with _ACTIVE_LOCK:
                    if not (arena and (mode == "pause" or _ACTIVE["n"] >= 1)):
                        _ACTIVE["n"] += 1
                        return True
                    if not counted:
                        _ACTIVE["waiting"] += 1
                        counted = True
                time.sleep(ARENA_POLL)
        finally:
            if counted:
                with _ACTIVE_LOCK:
                    _ACTIVE["waiting"] -= 1

    def _launch(self, cmd, forge_dir, segs, n, tmp, errf, seed, idx, attempt, java):
        flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0   # no console window, below-normal priority
        t0 = time.time()
        err = open(errf, "w", encoding="utf-8", errors="replace")
        p = subprocess.Popen(cmd, cwd=forge_dir, stdout=subprocess.PIPE, stderr=err,
                             text=True, creationflags=flags)
        with self.lock:
            self.procs.add(p)
            if self.stopping:   # Stop pressed while this one was starting
                p.kill()
        try:
            for line in p.stdout:
                if line.startswith("GAME_DONE"):
                    with self.lock:
                        self.done += 1
                elif line.startswith("DECK_ERROR"):
                    bad = line[len("DECK_ERROR"):].strip()
                    self.log(f"Forge couldn't read {Path(bad).name if bad else self.deck.name + ' or ' + segs[0][0].name}")
            p.wait(timeout=n * GAME_TIMEOUT + 120)
        except subprocess.TimeoutExpired:
            p.kill()
        finally:
            with self.lock:
                self.procs.discard(p)
            err.close()
        games, got = [], [0] * len(segs)
        if tmp.exists():
            for l in tmp.read_text(encoding="utf-8").splitlines():
                try:
                    g = json.loads(l)
                    slot = int(g.pop("slot", 0))
                    opp_path = segs[slot][0]
                except (ValueError, IndexError, TypeError):
                    continue
                k = got[slot]
                got[slot] += 1
                # "pair": which seeded slot this game came from, so runs with the same seed line up game by game
                g.update(pair=f"{opp_path.name}:{idx}:{k}", seed=seed, run=self.id, deck_a=self.deck.name,
                         label=self.label, format=self.fmt.key, ai=self.cfg.get("ai_profile", "Default"))
                games.append(g)
            tmp.unlink()
        for f in (self.out_dir / f".{self.id}-{idx}-{attempt}.opps",):
            try:
                f.unlink()
            except OSError:
                pass
        with self.lock, open(self.results, "a", encoding="utf-8") as f:
            for g in games:
                f.write(json.dumps(g, separators=(",", ":")) + "\n")
        missing = [(o, k - got[i]) for i, (o, k) in enumerate(segs) if k - got[i] > 0]
        short = sum(k for _, k in missing)
        if short > 0 and not self.stopping:
            # usually a busy PC: Java couldn't start or a game hung. Keep Forge's error output for diagnostics
            # and try the missing games once more before giving up on them.
            keep = self.cfg.home / "logs" / f"forge-{self.id}-{idx}-{attempt}.log"
            try:
                keep.parent.mkdir(parents=True, exist_ok=True)
                errf.replace(keep)
            except OSError:
                pass
            names = ", ".join(o.stem for o, _ in missing)
            if attempt == 1 and self._closed_outside(time.time() - t0):
                with self.lock:
                    self.missing += short
                    if "Forge was closed outside Brewbench, so the run stopped" not in self.problems:
                        self.problems.insert(0, "Forge was closed outside Brewbench, so the run stopped")
                return games
            if attempt == 1:
                self.log(f"{short} game(s) vs {names} didn't finish; trying them again")
                return _Retry(games, missing)   # retried by _batch once this batch's slot is free
            with self.lock:
                self.missing += short
                self.problems += [f"{k} vs {o.stem}" for o, k in missing]
            self.log(f"{short} game(s) vs {names} couldn't be played (Forge's output is in {keep})")
        else:
            try:
                errf.unlink()
            except OSError:
                pass
        return games

    def _closed_outside(self, ran_for):
        """True when several of this run's Java processes died together after running a while (e.g. ended in
        Task Manager): then the run stops instead of starting them all again. A single crash, or Java failing
        to start on a busy PC, still gets its retry."""
        if ran_for < SETTLED:
            return False
        now = time.time()
        with self.lock:
            self._fails.append(now)
        time.sleep(CLOSE_WINDOW / 3)       # let the others that went down at the same moment report in
        with self.lock:
            recent = sum(1 for t in self._fails if now - CLOSE_WINDOW <= t <= now + CLOSE_WINDOW)
            if recent >= min(3, max(1, self.instances)) and self.instances > 1:
                self.stopping = True
        return self.stopping

    def start(self, progress=None, waiting=None):
        """Plays the run. If another test is already running on this PC, waits for it first
        (waiting(True) / waiting(False) tell the caller)."""
        lock = SimLock(self.cfg.home / "sim.lock")
        wait = self.cfg.home / "sim.waiting"
        # fairness: if another test is queued, let it go first instead of grabbing the PC straight back
        try:
            if time.time() - wait.stat().st_mtime < WAITING_FRESH and wait.read_text().strip() != self.id:
                time.sleep(WAITING_FRESH)
        except (OSError, ValueError):
            pass
        if not lock.acquire():
            self.log("Another test is running on this PC; this one starts when it finishes.")
            if waiting:
                waiting(True)
            while not lock.acquire():
                try:
                    wait.write_text(self.id)     # "I'm next": see the check above
                except OSError:
                    pass
                if self.stopping:
                    if waiting:
                        waiting(False)
                    return []
                time.sleep(WAIT_POLL)
            if waiting:
                waiting(False)
        try:
            return self._start(progress)
        finally:
            lock.release()

    def _start(self, progress=None):
        forge_dir = self.cfg.forge_dir
        java = forge.find_java(forge_dir, self.cfg.get("java"))
        forge.prepare(forge_dir, self.cfg.get("ai_profile", "Default"))
        size = batch_size(self.games, self.instances)
        jobs = pack(plan(self.opponents, self.games, batch=size, weights=self.weights), size)
        self.log(f"{self.games} games of {self.fmt.name}: {self.deck.stem} vs {len(self.opponents)} "
                 f"opponent deck(s), {self.instances} at a time")
        meta = {"run": self.id, "label": self.label, "deck": str(self.deck), "format": self.fmt.key,
                "opponents": [str(o) for o in self.opponents], "games": self.games,
                "ai": self.cfg.get("ai_profile", "Default"), "seed": self.seed, "started": int(time.time())}
        (self.out_dir / f"{self.id}.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        all_games = []
        stop_progress = threading.Event()

        def ticker():
            while not stop_progress.wait(2):
                if progress:
                    progress(self.done, self.games)

        t = threading.Thread(target=ticker, daemon=True)
        t.start()
        try:
            with ThreadPoolExecutor(max_workers=self.instances) as ex:
                futs = [ex.submit(self._batch, java, forge_dir, segs, 0, i) for i, segs in enumerate(jobs)]
                for fu in as_completed(futs):
                    all_games += fu.result()
        except KeyboardInterrupt:
            self.stop()
            raise
        finally:
            stop_progress.set()
            if progress:
                progress(self.done, self.games)
        return all_games

    def stop(self):
        self.stopping = True
        with self.lock:
            procs = list(self.procs)
        for p in procs:
            try:
                p.kill()
            except OSError:
                pass
            if os.name == "nt":   # make sure the whole Java process tree goes
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                               creationflags=0x08000000)


def load_results(path_or_dir, run=None, label=None):
    p = Path(path_or_dir)
    files = [p] if p.is_file() else sorted(p.glob("*.jsonl"))
    out = []
    for f in files:
        for l in f.read_text(encoding="utf-8").splitlines():
            try:
                g = json.loads(l)
            except ValueError:
                continue
            if run and g.get("run") != run:
                continue
            if label and g.get("label") != label:
                continue
            out.append(g)
    return out


# ------------------------------------------------------------ every sim on this PC, whoever started it
# Runs started from the app are stopped through their Run object. Runs started from the command line (or the
# optimiser) are separate programs, so these find them by their command line: the Forge harness class, and the
# brewbench commands that keep launching new batches.
_DRIVER_MARKERS = (" run ", " compare ", " optimise ", " optimize ")


def _procs():
    """[(pid, command line)] for every process, best effort; [] if it can't be read."""
    out = []
    try:
        if os.name == "nt":
            ps = ("Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                               text=True, timeout=20, creationflags=0x08000000)
            lines = r.stdout.splitlines()
        else:
            r = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=10)
            lines = [l.strip().replace(" ", "\t", 1) for l in r.stdout.splitlines()]
        for l in lines:
            pid, _, cmd = l.partition("\t")
            if pid.strip().isdigit() and cmd:
                out.append((int(pid), cmd))
    except Exception:
        pass
    return out


def _is_sim(cmd):
    """A Forge game process: java running the Brewbench harness class."""
    import re
    return "java" in cmd.lower() and re.search(r"\s(brewbench|mtgasim)\.Sim(\s|$)", cmd) is not None


def _is_driver(cmd):
    c = " " + cmd.replace('"', " ") + " "
    return (("brewbench" in c or "mtgasim" in c) and any(m in c for m in _DRIVER_MARKERS)
            and " serve " not in c and " app " not in c)


def find_sims():
    """{'games': n Forge processes, 'drivers': n brewbench run/compare/optimise commands} running right now."""
    me = os.getpid()
    procs = [(p, c) for p, c in _procs() if p != me]
    return {"games": sum(1 for _, c in procs if _is_sim(c)),
            "drivers": sum(1 for _, c in procs if _is_driver(c))}


def kill_all_sims():
    """Stops every Brewbench sim on this PC: the commands that launch batches first (so nothing new starts),
    then the Forge games. Returns how many processes were ended."""
    me = os.getpid()
    procs = [(p, c) for p, c in _procs() if p != me]
    targets = [p for p, c in procs if _is_driver(c)] + [p for p, c in procs if _is_sim(c)]
    n = 0
    for pid in targets:
        try:
            if os.name == "nt":
                r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                                   creationflags=0x08000000)
                n += r.returncode == 0
            else:
                os.kill(pid, 9)
                n += 1
        except OSError:
            pass
    return n
