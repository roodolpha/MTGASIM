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
