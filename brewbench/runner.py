"""Runs many Forge games in parallel: your deck against a gauntlet of opponent decks.

Work is split into batches (one Java process plays a batch of games against one opponent, because starting
Forge costs several seconds). Batches are spread evenly over the gauntlet, so every opponent gets close to
the same number of games."""
import json
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import forge

BATCH = 10            # games per Java start-up
GAME_TIMEOUT = 180    # seconds before a stuck game counts as a draw


def plan(opponents, games, batch=BATCH):
    """[(opponent, n_games)] covering `games` games, round-robin over the opponents."""
    if not opponents:
        return []
    per = [0] * len(opponents)
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

    def _batch(self, java, forge_dir, opp, n, idx, attempt=1):
        if self.stopping:   # queued batches after Stop: don't start them
            return []
        tmp = self.out_dir / f".{self.id}-{idx}-{attempt}.part"
        errf = self.out_dir / f".{self.id}-{idx}-{attempt}.err"
        seed = None if self.seed is None else self.seed + idx
        cmd = forge.command(java, forge_dir, self.fmt, self.deck.resolve(), opp.resolve(), n, tmp.resolve(),
                            GAME_TIMEOUT, seed)
        flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0   # no console window, below-normal priority
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
                    self.log(f"Forge couldn't read {self.deck.name} or {opp.name}")
            p.wait(timeout=n * GAME_TIMEOUT + 120)
        except subprocess.TimeoutExpired:
            p.kill()
        finally:
            with self.lock:
                self.procs.discard(p)
            err.close()
        games = []
        if tmp.exists():
            for k, l in enumerate(tmp.read_text(encoding="utf-8").splitlines()):
                try:
                    g = json.loads(l)
                except ValueError:
                    continue
                # "pair": which seeded slot this game came from, so runs with the same seed line up game by game
                g.update(pair=f"{opp.name}:{idx}:{k}", seed=seed, run=self.id, deck_a=self.deck.name, label=self.label, format=self.fmt.key,
                         ai=self.cfg.get("ai_profile", "Default"))
                games.append(g)
            tmp.unlink()
        with self.lock, open(self.results, "a", encoding="utf-8") as f:
            for g in games:
                f.write(json.dumps(g, separators=(",", ":")) + "\n")
        short = n - len(games)
        if short > 0 and not self.stopping:
            # usually a busy PC: Java couldn't start or a game hung. Keep Forge's error output for diagnostics
            # and try the missing games once more before giving up on them.
            keep = self.cfg.home / "logs" / f"forge-{self.id}-{idx}-{attempt}.log"
            try:
                keep.parent.mkdir(parents=True, exist_ok=True)
                errf.replace(keep)
            except OSError:
                pass
            if attempt == 1:
                self.log(f"{short} game(s) vs {opp.stem} didn't finish; trying them again")
                return games + self._batch(java, forge_dir, opp, short, idx + 10000, attempt=2)
            with self.lock:
                self.missing += short
                self.problems.append(f"{short} vs {opp.stem}")
            self.log(f"{short} game(s) vs {opp.stem} couldn't be played (Forge's output is in {keep})")
        else:
            try:
                errf.unlink()
            except OSError:
                pass
        return games

    def start(self, progress=None):
        forge_dir = self.cfg.forge_dir
        java = forge.find_java(forge_dir, self.cfg.get("java"))
        forge.prepare(forge_dir, self.cfg.get("ai_profile", "Default"))
        jobs = plan(self.opponents, self.games)
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
                futs = [ex.submit(self._batch, java, forge_dir, opp, n, i) for i, (opp, n) in enumerate(jobs)]
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
