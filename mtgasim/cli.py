"""mtgasim: simulate your MTG Arena decks with Forge's AI.

  mtgasim setup --forge-dir "C:\\Games\\Forge"
  mtgasim deck import my_deck.txt --name "Mono Red"
  mtgasim deck from-log
  mtgasim gauntlet add standard meta_deck.txt
  mtgasim run "Mono Red" --format standard --games 500
  mtgasim compare "Mono Red" "Mono Red v2" --format standard --games 1000
  mtgasim report
"""
import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, decks as D, formats, forge, gauntlet, runner, stats
from .config import Config


def pct(x):
    return "  -  " if x is None else f"{100 * x:5.1f}%"


def resolve_deck(cfg, ref):
    """A path, or the name of a deck saved with `deck import`."""
    p = Path(ref)
    if p.exists():
        if p.suffix.lower() != ".dck":   # Arena text: convert it into the decks folder first
            deck = D.load(p)
            return deck.save(cfg.decks_dir / f"{gauntlet.slug(deck.name)}.dck")
        return p
    cand = cfg.decks_dir / f"{gauntlet.slug(ref)}.dck"
    if cand.exists():
        return cand
    raise SystemExit(f"No deck called {ref!r}. Saved decks: "
                     + (", ".join(d.stem for d in sorted(cfg.decks_dir.glob('*.dck'))) or "none yet"))


def resolve_opponents(cfg, fmt, vs):
    if not vs:
        opps = gauntlet.list_decks(cfg.gauntlet_dir(fmt.key))
        if not opps:
            raise SystemExit(f"Your {fmt.name} gauntlet is empty. Add decks with: "
                             f"mtgasim gauntlet add {fmt.key} <decklist>")
        return opps
    out = []
    for v in vs:
        p = Path(v)
        out += gauntlet.list_decks(p) if p.is_dir() else [resolve_deck(cfg, v)]
    return out


def print_summary(title, games):
    s = stats.summary(games)
    lo, hi = s["ci95"]
    print(f"\n{title}")
    print(f"  {s['games']} games: {s['wins']}W {s['losses']}L {s['draws']}D"
          + (f" ({s['errors']} errored, not counted)" if s["errors"] else ""))
    if s["win_rate"] is not None:
        print(f"  Win rate {pct(s['win_rate'])}  (95% range {pct(lo)} to {pct(hi)})")
        print(f"  On the play {pct(s['on_play'])}   on the draw {pct(s['on_draw'])}"
              + (f"   average game {s['avg_turns']:.0f} turns (both players)" if s["avg_turns"] else ""))
    rows = stats.by_opponent(games)
    if len(rows) > 1:
        print("\n  Against each opponent (worst first):")
        w = max(len(r["opponent"]) for r in rows)
        for r in rows:
            print(f"    {r['opponent']:<{w}}  {pct(r['win_rate'])}  ({r['games']} games)")


# ------------------------------------------------------------------ commands
def cmd_setup(cfg, a):
    if a.forge_dir:
        d = Path(a.forge_dir).expanduser()
        forge.forge_jar(d)
        cfg.set("forge_dir", str(d.resolve()))
    if a.java:
        cfg.set("java", a.java)
    if a.ai:
        cfg.set("ai_profile", a.ai)
    if a.instances:
        cfg.set("instances", a.instances)
    if a.arena_log:
        cfg.set("arena_log", a.arena_log)
    if a.build_harness:
        print("Built", forge.build_harness(cfg.forge_dir))
    return cmd_doctor(cfg, a)


def cmd_doctor(cfg, a):
    ok = True
    print(f"MTGASIM {__version__}   files in {cfg.home}")
    try:
        fd = cfg.forge_dir
        v = forge.forge_version(fd)
        note = "" if v == forge.FORGE_VERSION else f"  (harness was built for {forge.FORGE_VERSION}; " \
                                                   "run `mtgasim setup --build-harness` if games error)"
        print(f"  Forge     {v} at {fd}{note}")
        profs = forge.ai_profiles(fd)
        print(f"  AI        {cfg.get('ai_profile', 'Default')}   (available: {', '.join(profs) or '?'})")
    except forge.SetupError as e:
        print("  Forge     not set up:", e)
        ok, fd = False, None
    try:
        j = forge.find_java(fd, cfg.get("java"))
        m = forge.java_major(j)
        print(f"  Java      {m or '?'} at {j}" + ("" if m >= 17 else "   needs 17 or newer"))
        ok = ok and m >= 17
    except forge.SetupError as e:
        print("  Java     ", e)
        ok = False
    print(f"  Harness   {'found' if forge.HARNESS_JAR.exists() else 'missing'} ({forge.HARNESS_JAR})")
    ok = ok and forge.HARNESS_JAR.exists()
    from . import arena_log
    logs = arena_log.find_logs(cfg.get("arena_log"))
    print(f"  Arena log {logs[-1] if logs else 'not found (only needed for deck from-log)'}")
    print(f"  Parallel  {cfg.get('instances') or 'auto'} games at a time")
    print("\nReady." if ok else "\nNot ready yet: fix the lines above.")
    return 0 if ok else 1


def cmd_deck_import(cfg, a):
    src = sys.stdin.read() if a.source == "-" else a.source
    deck = D.load(src, a.name)
    if a.name:
        deck.name = a.name
    path = deck.save(cfg.decks_dir / f"{gauntlet.slug(deck.name)}.dck")
    print(f"Saved {deck.name}: {deck.size} cards" + (f" + {', '.join(deck.commanders)}" if deck.commanders else "")
          + f" -> {path}")
    if a.format:
        _check(cfg, deck, formats.get(a.format))


def _check(cfg, deck, fmt):
    try:
        names = forge.card_names(cfg.forge_dir)
    except forge.SetupError:
        names = None
    from . import cards
    legal = cards.legality(deck.all_names(), fmt.scryfall, cfg.cache_dir / "legality.json")
    problems = D.check(deck, fmt, names, legal)
    if names:
        flagged = sorted((set(deck.main) | set(deck.commanders)) & forge.ai_flagged(cfg.forge_dir))
        if flagged:
            problems.append("Forge's AI is known to play these badly, so results may undersell them: "
                            + ", ".join(flagged))
    print("\n".join(f"  ! {p}" for p in problems) if problems else f"  Looks fine for {fmt.name}.")


def cmd_deck_check(cfg, a):
    _check(cfg, D.load(resolve_deck(cfg, a.deck)), formats.get(a.format))


def cmd_deck_list(cfg, a):
    for p in sorted(cfg.decks_dir.glob("*.dck")):
        d = D.read_dck(p)
        print(f"  {p.stem:<32} {d.size:>3} cards" + (f"  ({', '.join(d.commanders)})" if d.commanders else ""))


def cmd_deck_from_log(cfg, a):
    from . import arena_log, cards
    logs = arena_log.find_logs(cfg.get("arena_log"))
    if not logs:
        raise SystemExit("Couldn't find Arena's Player.log. Turn on Detailed Logs in Arena, play a game, "
                         "or pass the path with `mtgasim setup --arena-log`.")
    r = arena_log.read_all(logs)
    book = cards.CardBook(cfg.cache_dir / "cards.json")
    latest = {}
    for d in r.decks.values():   # keep the newest version of each deck
        if d.deck_id not in latest or d.saved >= latest[d.deck_id].saved:
            latest[d.deck_id] = d
    found = sorted(latest.values(), key=lambda d: d.saved, reverse=True)
    if not found:
        raise SystemExit("No decks in the log yet: open a deck in Arena's deck builder or queue with one.")
    for i, d in enumerate(found, 1):
        print(f"  {i:>2}. {d.name}  ({len(d.cards)} cards, saved {d.saved or '?'})")
    picks = range(1, len(found) + 1) if a.all else ([a.pick] if a.pick else [])
    for k in picks:
        d = found[k - 1]
        deck = D.Deck(name=d.name, commanders=[D.clean_name(book.name(c) or f"#{c}") for c in d.commanders])
        for g in d.cards:
            deck.main[D.clean_name(book.name(g) or f"#{g}")] += 1
        path = deck.save(cfg.decks_dir / f"{gauntlet.slug(d.name)}.dck")
        print(f"Saved {d.name} -> {path}")
    book.save()
    if not picks:
        print("\nSave one with: mtgasim deck from-log --pick <number>   (or --all)")


def cmd_gauntlet_add(cfg, a):
    fmt = formats.get(a.format)
    srcs = gauntlet.expand_sources(a.source)
    for src in srcs:
        path, deck = gauntlet.add(cfg.gauntlet_dir(fmt.key), src, a.name if len(srcs) == 1 else None)
        print(f"Added {deck.name} ({deck.size} cards) to the {fmt.name} gauntlet")


def cmd_gauntlet_list(cfg, a):
    fmts = [formats.get(a.format)] if a.format else formats.FORMATS.values()
    for fmt in fmts:
        ds = gauntlet.list_decks(cfg.gauntlet_dir(fmt.key))
        if ds or a.format:
            print(f"{fmt.name}: {len(ds)} deck(s)")
            for p in ds:
                print("   ", p.stem)


def cmd_gauntlet_from_log(cfg, a):
    from . import arena_log, cards
    logs = arena_log.find_logs(cfg.get("arena_log"))
    if not logs:
        raise SystemExit("Couldn't find Arena's Player.log.")
    print("Building one deck per commander you've faced (takes a while: it looks up each list)...")
    made = gauntlet.from_log(arena_log.read_all(logs), cards.CardBook(cfg.cache_dir / "cards.json"),
                             cfg.gauntlet_dir("brawl"), forge.card_names(cfg.forge_dir))
    print(f"{len(made)} Brawl opponent deck(s) in {cfg.gauntlet_dir('brawl')}")


def _progress(done, total):
    bar = int(30 * done / total) if total else 0
    print(f"\r  [{'#' * bar}{'.' * (30 - bar)}] {done}/{total} games", end="", flush=True)


def cmd_run(cfg, a):
    fmt = formats.get(a.format)
    deck = resolve_deck(cfg, a.deck)
    opps = resolve_opponents(cfg, fmt, a.vs)
    r = runner.Run(cfg, fmt, deck, opps, a.games, a.instances, a.seed, a.label)
    games = r.start(_progress)
    print_summary(f"{r.label} ({fmt.name}, AI: {cfg.get('ai_profile', 'Default')})", games)
    print(f"\n  Results: {r.results}")


def cmd_compare(cfg, a):
    """Same gauntlet, same seeds for both decks, so the comparison is as fair as Forge allows."""
    fmt = formats.get(a.format)
    da, db = resolve_deck(cfg, a.deck_a), resolve_deck(cfg, a.deck_b)
    opps = resolve_opponents(cfg, fmt, a.vs)
    seed = a.seed if a.seed is not None else 1000
    res = []
    for d in (da, db):
        r = runner.Run(cfg, fmt, d, opps, a.games, a.instances, seed, d.stem)
        res.append(r.start(_progress))
        print_summary(d.stem, res[-1])
    c = stats.compare(*res)
    if c["diff"] is None:
        return 1
    print(f"\n{da.stem} vs {db.stem}: {100 * c['diff']:+.1f} points (z = {c['z']:.2f})")
    if c["p_value"] < 0.05:
        print(f"  {da.stem} is very likely better against this gauntlet (p = {c['p_value']:.3f}).")
    elif c["p_value"] > 0.95:
        print(f"  {db.stem} is very likely better against this gauntlet (p = {1 - c['p_value']:.3f}).")
    else:
        need = stats.games_needed(max(abs(c["diff"]), 0.01))
        print(f"  Too close to call. Telling a gap this size apart takes about {need} games per deck.")


def cmd_optimise(cfg, a):
    from . import optimiser
    fmt = formats.get(a.format)
    deck = resolve_deck(cfg, a.deck)
    opps = resolve_opponents(cfg, fmt, a.vs)
    pool = []
    for src in a.pool or []:
        p = Path(src)
        if p.exists():
            d = D.load(p)
            pool += list(d.main) + list(d.side)
        else:
            pool.append(src)
    if not pool:
        d = D.read_dck(deck)
        pool = list(d.side)
    if not pool:
        raise SystemExit("Give cards to try with --pool (a list file, a deck, or card names), "
                         "or put them in the deck's sideboard.")
    opt = optimiser.Optimiser(cfg, fmt, deck, opps, pool, outs=a.cut, protect=a.keep or (), instances=a.instances,
                              screen=a.screen, confirm=a.confirm, holdout=a.holdout)
    print(f"Optimising {deck.stem}: {len(pool)} card(s) to try, {len(opt.train)} tuning opponents, "
          f"{len(opt.hold)} held out.")
    until = time.time() + a.hours * 3600 if a.hours else None
    print(opt.run(max_tests=a.max_tests, until=until))


def cmd_serve(cfg, a):
    from . import server
    server.serve(cfg, a.port, open_browser=not a.no_browser, track=not a.no_track)


def cmd_track(cfg, a):
    from . import tracker
    if a.import_from:
        print("Copied: " + ", ".join(tracker.import_old_tracker(cfg, a.import_from)))
        print(f"Rebuilt the stats for {tracker.rebuild(cfg)} games.")
        return
    print("Watching Arena's log for games (Ctrl+C to stop)...")
    tracker.run(cfg)


def cmd_share(cfg, a):
    from . import share
    c = share.Client(cfg, a.api)
    if a.forget:
        if not c.registered:
            raise SystemExit("Nothing to forget: you haven't shared anything from this PC.")
        c.forget()
        print("Done: everything you uploaded has been deleted from the site, and this PC is unlinked.")
        return
    if a.preview:
        p = share.build_payload(cfg, a.lists)
        print(json.dumps({k: v[:3] for k, v in p.items()}, indent=1))
        print(f"\n{len(p['matches'])} real games, {len(p['sims'])} simulator summaries, {len(p['decks'])} lists would be sent.")
        return
    if not c.registered:
        if not a.yes:
            print(share.__doc__)
            if input("Share? [y/N] ").strip().lower() != "y":
                return
        c.register(a.name, a.public)
        print("Linked this PC" + (f" as {a.name}" + (" (public)" if a.public else " (hidden)") if a.name else " anonymously"))
    elif a.name is not None or a.public:
        c.update(a.name or cfg.get("share_name"), a.public)
    r = c.upload(share.build_payload(cfg, a.lists))
    print(f"Sent {r['matches']} real games, {r['sims']} simulator summaries, {r['decks']} lists"
          + (f" ({r['rejected']} rows skipped)" if r["rejected"] else "") + ".")


def cmd_report(cfg, a):
    rd = cfg.results_dir
    metas = sorted(rd.glob("*.meta.json"))
    if not metas:
        raise SystemExit("No runs yet.")
    if not a.run:
        for m in metas[-15:]:
            d = json.loads(m.read_text(encoding="utf-8"))
            s = stats.summary(runner.load_results(rd / f"{d['run']}.jsonl")) if (rd / f"{d['run']}.jsonl").exists() else None
            print(f"  {d['run']}  {d['label']:<28} {d['format']:<10} "
                  + (f"{pct(s['win_rate'])} over {s['games']}" if s else "no games"))
        print("\nDetail: mtgasim report <run id>")
        return
    games = runner.load_results(rd / f"{a.run}.jsonl")
    print_summary(a.run, games)


def main(argv=None):
    p = argparse.ArgumentParser(prog="mtgasim", description="Simulate your MTG Arena decks with Forge's AI.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--home", help="where MTGASIM keeps its files (default ~/.mtgasim)")
    sub = p.add_subparsers(dest="cmd", required=True)
    fmt_help = "format: " + ", ".join(formats.FORMATS)

    s = sub.add_parser("setup", help="point MTGASIM at Forge and Java")
    s.add_argument("--forge-dir")
    s.add_argument("--java")
    s.add_argument("--ai", help="Forge AI profile (see `mtgasim doctor`)")
    s.add_argument("--instances", type=int, help="games to run at once")
    s.add_argument("--arena-log")
    s.add_argument("--build-harness", action="store_true", help="recompile the Java harness (needs a JDK)")
    s.set_defaults(fn=cmd_setup)
    sub.add_parser("doctor", help="check everything is in place").set_defaults(fn=cmd_doctor)

    dk = sub.add_parser("deck", help="your decks").add_subparsers(dest="sub", required=True)
    s = dk.add_parser("import", help="save an Arena export (file, or - to paste)")
    s.add_argument("source")
    s.add_argument("--name")
    s.add_argument("--format", help="also check the deck: " + fmt_help)
    s.set_defaults(fn=cmd_deck_import)
    s = dk.add_parser("check", help="check a deck against a format and what Forge can play")
    s.add_argument("deck")
    s.add_argument("--format", required=True, help=fmt_help)
    s.set_defaults(fn=cmd_deck_check)
    dk.add_parser("list", help="saved decks").set_defaults(fn=cmd_deck_list)
    s = dk.add_parser("from-log", help="decks you've saved or played with in Arena")
    s.add_argument("--pick", type=int)
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_deck_from_log)

    g = sub.add_parser("gauntlet", help="opponent decks").add_subparsers(dest="sub", required=True)
    s = g.add_parser("add", help="add decklists to a format's gauntlet")
    s.add_argument("format", help=fmt_help)
    s.add_argument("source", nargs="+")
    s.add_argument("--name")
    s.set_defaults(fn=cmd_gauntlet_add)
    s = g.add_parser("list")
    s.add_argument("format", nargs="?")
    s.set_defaults(fn=cmd_gauntlet_list)
    g.add_parser("from-log", help="Brawl: a deck for every commander you've faced").set_defaults(fn=cmd_gauntlet_from_log)

    for name, fn, two in (("run", cmd_run, False), ("compare", cmd_compare, True)):
        s = sub.add_parser(name, help="simulate a deck against a gauntlet" if not two
                           else "A/B test two versions of a deck on the same gauntlet")
        if two:
            s.add_argument("deck_a")
            s.add_argument("deck_b")
        else:
            s.add_argument("deck")
            s.add_argument("--label")
        s.add_argument("--format", "-f", required=True, help=fmt_help)
        s.add_argument("--games", "-n", type=int, default=200)
        s.add_argument("--vs", nargs="*", help="opponent decks or folders (default: the format's gauntlet)")
        s.add_argument("--instances", "-j", type=int)
        s.add_argument("--seed", type=int)
        s.set_defaults(fn=fn)

    s = sub.add_parser("optimise", aliases=["optimize"], help="test one-card swaps and keep the ones that help")
    s.add_argument("deck")
    s.add_argument("--format", "-f", required=True, help=fmt_help)
    s.add_argument("--pool", nargs="*", help="cards to try: a list file, a deck file, or names (default: the deck's sideboard)")
    s.add_argument("--cut", nargs="*", help="cards to try cutting first")
    s.add_argument("--keep", nargs="*", help="cards never to cut")
    s.add_argument("--vs", nargs="*")
    s.add_argument("--instances", "-j", type=int)
    s.add_argument("--max-tests", type=int, help="stop after this many swaps")
    s.add_argument("--hours", type=float, help="stop after this long")
    s.add_argument("--screen", type=int, default=200, help="games per screening run")
    s.add_argument("--confirm", type=int, default=800, help="games per confirming run")
    s.add_argument("--holdout", type=int, default=400, help="games per hold-out run")
    s.set_defaults(fn=cmd_optimise)

    s = sub.add_parser("serve", help="open the local dashboard")
    s.add_argument("--port", type=int, default=8780)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--no-track", action="store_true", help="don't watch Arena's log for games")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("track", help="record your Arena games from the log (serve does this too)")
    s.add_argument("--import-from", metavar="FOLDER", help="bring in history from an Arena Tracker folder")
    s.set_defaults(fn=cmd_track)

    s = sub.add_parser("share", help="opt in: send your results to the public site")
    s.add_argument("--name", help="display name on the site (leave out to stay anonymous)")
    s.add_argument("--public", action="store_true", help="show you on leaderboards (needs --name)")
    s.add_argument("--lists", action="store_true", help="also share your decklists")
    s.add_argument("--preview", action="store_true", help="show what would be sent, send nothing")
    s.add_argument("--forget", action="store_true", help="delete everything you've sent")
    s.add_argument("--yes", "-y", action="store_true")
    s.add_argument("--api", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_share)

    s = sub.add_parser("report", help="past runs")
    s.add_argument("run", nargs="?")
    s.set_defaults(fn=cmd_report)

    a = p.parse_args(argv)
    cfg = Config(a.home)
    try:
        return a.fn(cfg, a) or 0
    except forge.SetupError as e:
        print(e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
