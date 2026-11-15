# Roadmap

Matches the product plan's phases. Ticked items are in the repo.

## Phase 1: public simulator core (this release, 0.1)
- [x] Java harness: Brawl and constructed (60-card) games, per-turn board snapshots, optional seed
- [x] Arena export text and Forge .dck reading/writing; format checks (size, copies, Forge coverage, legality, AI-flagged cards)
- [x] Arena log reader: saved decks, matches, opponents' cards and commanders
- [x] Parallel runner spread evenly over a gauntlet; results as JSON lines
- [x] Stats: Wilson intervals, play/draw split, per-matchup table, A/B test with games-needed estimate
- [x] CLI: setup, doctor, deck, gauntlet, run, compare, report
- [ ] Windows one-click launcher and bundled Java
- [ ] Pause simulation while Arena is in a match

## Phase 2: local app
- [ ] Local web dashboard (runs, matchups, deck versions over time)
- [ ] Optimiser: test single-card swaps automatically (screen, confirm, hold-out check)
- [ ] Meta gauntlets for Standard/Historic from public decklists

## Phase 3+: website
- [ ] Opt-in upload of anonymised simulation results
- [ ] Public leaderboards and meta pages by format; public read API
