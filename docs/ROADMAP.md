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

## Phase 2: local app (0.2)
- [x] Local web dashboard: runs, matchups, card hints, decks, optimiser, start/stop runs (`brewbench serve`)
- [x] Optimiser: paired single-card swaps, screen / confirm / hold-out, resumable (`brewbench optimise`)
- [x] Paired statistics: seeded runs line up game by game
- [x] Gauntlets from whole folders of decklists
- [ ] Meta gauntlets for Standard/Historic pulled from public decklists automatically
- [ ] Windows installer with Java bundled

## Phase 3: website (0.2, not deployed yet)
- [x] Opt-in sharing from the simulator: register, upload, rename, forget (`brewbench share`)
- [x] API on Cloudflare Workers + D1: upload, leaderboards, meta, matchups, player pages (`server/`)
- [x] Static public site reading the API (`site/`), docs in `docs/API.md`, deploy steps in `docs/HOSTING.md`
- [ ] Deploy (needs the name/domain decided)
- [ ] Archetype names for constructed decks (beyond colours)
- [ ] Remaining site pages restyled to match the new home page
