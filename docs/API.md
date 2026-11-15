# Brewbench public API

Free, open, no key. JSON over HTTPS. Responses are cached for 5 minutes, so polling faster than that gets you
nothing new. CORS is open: call it straight from a browser.

Base URL: `https://api.brewbench.gg` (placeholder until the site launches).

Win rates are fractions (0.55 = 55%). Draws count as half a win. `ci95` is a 95% Wilson interval: where the
true win rate probably sits given the number of games. Brawl formats are grouped by commander; constructed
formats by colours (`"UB"`, `"BRG"`, WUBRG order) until archetype naming lands.

## GET /v1/formats

`{"formats": ["brawl", "standardbrawl", "standard", "historic", "timeless", "alchemy"]}`

## GET /v1/meta?format=standard&days=30

Every deck seen in the window, most played first.

```json
{"format": "standard", "since": "2026-10-16", "real_games": 18234,
 "decks": [{"deck": "R", "colours": "R", "share": 0.17,
            "real": {"games": 3100, "win_rate": 0.58, "ci95": [0.562, 0.597]},
            "sim":  {"games": 120000, "win_rate": 0.60}}]}
```

`real` is null for decks only seen in simulations, `sim` is null for decks nobody has simulated yet.

## GET /v1/matchups?format=historic&days=30&top=8

The `top` most-seen decks (as played or as opponents) and a grid of row-vs-column results.

```json
{"decks": ["BR", "BRG"], "grid": [[{"real": null, "sim": null},
                                   {"real": {"games": 40, "win_rate": 0.55}, "sim": {"games": 900, "win_rate": 0.52}}], ...]}
```

## GET /v1/leaderboard?format=brawl&days=30&min=50

Players who chose a public display name, with at least `min` games in the window, best win rate first (top 100).

```json
{"players": [{"pos": 1, "name": "Someone", "games": 804, "wins": 490, "draws": 0,
              "win_rate": 0.609, "ci95": [0.575, 0.643], "main_deck": "Tam, Mindful First-Year", "colours": "UG"}]}
```

## GET /v1/players/{name}?format=brawl

A public player's history: weekly win rate (last 26 weeks), decks they've played, and opponents faced at
least 5 times. 404 if there's no public player by that name.

## Uploading (what the simulator does)

`POST /v1/register` with `{"display_name": "optional", "public": false}` returns `{"client_id", "key"}`.
Then `POST /v1/upload` with `Authorization: Bearer <client_id>:<key>` and
`{"matches": [...], "sims": [...], "decks": [...]}` (up to 1,000 of each per request; see `server/src/index.js`
for the fields). `PATCH /v1/me` changes the display name or public flag; `DELETE /v1/me` deletes everything
that uploader has sent. Shared decklists aren't tied to anyone and stay.

## Fair use

Be gentle: cache, and don't hammer it. If you build something with it, a link back is appreciated.
