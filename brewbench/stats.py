"""Win rates with honest error bars, and whether one deck is really better than another."""
import math
from collections import defaultdict


def wilson(wins, n, z=1.96):
    """95% interval for a win rate (Wilson score; behaves well for small samples and near 0%/100%)."""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def score(games):
    """Draws count as half a win, the usual convention."""
    w = sum(1 for g in games if g.get("result") == "Win")
    d = sum(1 for g in games if g.get("result") == "Draw")
    n = sum(1 for g in games if g.get("result") in ("Win", "Loss", "Draw"))
    return w + 0.5 * d, n


def summary(games):
    s, n = score(games)
    lo, hi = wilson(s, n)
    turns = [g.get("turns", 0) for g in games if g.get("turns")]
    first = [g for g in games if g.get("first") == "a"]
    second = [g for g in games if g.get("first") == "b"]
    fs, fn = score(first)
    ss, sn = score(second)
    return {
        "games": n, "wins": sum(1 for g in games if g.get("result") == "Win"),
        "losses": sum(1 for g in games if g.get("result") == "Loss"),
        "draws": sum(1 for g in games if g.get("result") == "Draw"),
        "errors": sum(1 for g in games if g.get("result") == "Error"),
        "win_rate": s / n if n else None, "ci95": (lo, hi),
        "on_play": fs / fn if fn else None, "on_draw": ss / sn if sn else None,
        "avg_turns": sum(turns) / len(turns) if turns else None,
    }


def by_opponent(games):
    groups = defaultdict(list)
    for g in games:
        groups[g.get("deck_b", "?")].append(g)
    rows = []
    for opp, gs in groups.items():
        s = summary(gs)
        rows.append({"opponent": opp.rsplit(".", 1)[0], **s})
    rows.sort(key=lambda r: (r["win_rate"] if r["win_rate"] is not None else 2))
    return rows


def compare(games_a, games_b):
    """Two-proportion z-test: is deck A's win rate different from deck B's (same gauntlet)?
    Returns difference (A - B), z, and a one-sided p-value (small = A really is better)."""
    sa, na = score(games_a)
    sb, nb = score(games_b)
    if not na or not nb:
        return {"diff": None, "z": None, "p_value": None}
    pa, pb = sa / na, sb / nb
    p = (sa + sb) / (na + nb)
    se = math.sqrt(p * (1 - p) * (1 / na + 1 / nb)) or 1e-9
    z = (pa - pb) / se
    p_value = 0.5 * math.erfc(z / math.sqrt(2))
    return {"a": pa, "b": pb, "na": na, "nb": nb, "diff": pa - pb, "z": z, "p_value": p_value}


def games_needed(diff=0.03, base=0.5, z=1.96):
    """Roughly how many games per deck it takes to tell two decks apart by `diff`."""
    return math.ceil(2 * z * z * base * (1 - base) / (diff * diff))


def _points(g):
    return {"Win": 1.0, "Draw": 0.5, "Loss": 0.0}.get(g.get("result"))


def paired(games_a, games_b):
    """Compare two decks played on the same seeds: game i of A is matched with game i of B ("pair" key).
    Each pair cancels out the shuffle and opponent, so far fewer games are needed than an unpaired test.
    Returns the mean difference (A - B), its z-score and a one-sided p-value (small = A is better)."""
    b_by = {g["pair"]: _points(g) for g in games_b if g.get("pair") and _points(g) is not None}
    diffs = [_points(g) - b_by[g["pair"]] for g in games_a
             if g.get("pair") in b_by and _points(g) is not None]
    n = len(diffs)
    if n < 2:
        return {"n": n, "diff": None, "z": None, "p_value": None}
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    se = math.sqrt(var / n) or 1e-9
    z = mean / se
    return {"n": n, "diff": mean, "z": z, "p_value": 0.5 * math.erfc(z / math.sqrt(2)),
            "changed": sum(1 for d in diffs if d != 0)}


def card_presence(games, side="a"):
    """For each permanent that reached the battlefield: win rate in games where it did vs games where it didn't.
    Only permanents show up (instants and sorceries never sit on the battlefield), and it's correlation,
    not cause: cheap cards land more often, so treat it as a hint for what to test, nothing more."""
    seen_in = {}
    pts = []
    for i, g in enumerate(games):
        p = _points(g)
        if p is None:
            continue
        pts.append(p)
        names = set()
        for st in g.get("states") or []:
            for perm in (st.get(side) or {}).get("perms", []):
                if not perm[5]:   # tokens aren't deck cards
                    names.add(perm[0])
        for n in names:
            seen_in.setdefault(n, []).append(p)
    total, n_all = sum(pts), len(pts)
    out = {}
    for name, ps in seen_in.items():
        k = len(ps)
        if k == n_all:
            continue
        on, off = sum(ps) / k, (total - sum(ps)) / (n_all - k)
        out[name] = {"games_seen": k, "win_seen": on, "win_not_seen": off, "delta": on - off}
    return out
