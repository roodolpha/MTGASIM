# MTGASIM

Simulate your MTG Arena decks before you spend wildcards on them.

MTGASIM takes a decklist (pasted from Arena's Export button, or read straight from your Arena log) and plays
hundreds of games against a gauntlet of opponent decks, using the AI from [Forge](https://github.com/Card-Forge/forge),
the open-source Magic rules engine. You get a win rate with an honest error bar, how you do on the play and on
the draw, and which matchups are your worst. You can also A/B test two versions of a deck on the same gauntlet
to see whether a change actually helped.

**Formats:** Brawl (Historic Brawl), Standard Brawl, Standard, Historic, Timeless, Alchemy. Alchemy's rebalanced
digital cards mostly aren't in Forge; `deck check` tells you which cards would be left out.

MTGASIM only reads Arena's log file. It never touches the game client, its memory, or its network traffic,
and it gives no advice during games.

## What it is and isn't

Forge's AI is a competent but imperfect player. It misplays some cards (Forge marks many of them itself, and
`deck check` lists any in your deck), so treat results as *relative* evidence: "version B beats version A on
this gauntlet by 4 points" is far more trustworthy than "this deck is a 57% deck on ladder".

Win rates need many games. Telling a 3-point difference apart takes about 2,000 games per deck; `compare`
tells you when a result is still too close to call.

## Setup

1. **Java 17 or newer.** [Adoptium](https://adoptium.net) is fine.
2. **Forge 2.0.16.** Download the desktop build from [Forge's releases](https://github.com/Card-Forge/forge/releases)
   and unpack it anywhere. (Other versions may work; if games all come back as errors, run
   `mtgasim setup --build-harness` with a JDK installed.)
3. **MTGASIM** (Python 3.9+):

   ```
   pip install git+https://github.com/roodolpha/MTGASIM.git
   mtgasim setup --forge-dir "C:\Games\Forge"
   mtgasim doctor
   ```

4. **Optional:** in Arena, turn on *Options > Account > Detailed Logs (Plugin Support)* so MTGASIM can read
   your decks and the opponents you've faced.

## Use

```
# your deck
mtgasim deck import my_deck.txt --name "Izzet Prowess" --format standard
mtgasim deck from-log                 # list decks from your Arena log
mtgasim deck from-log --pick 1

# opponents
mtgasim gauntlet add standard mono_red.txt dimir_midrange.txt domain.txt
mtgasim gauntlet from-log             # Brawl: one deck per commander you've faced

# simulate
mtgasim run "Izzet Prowess" -f standard -n 500
mtgasim compare "Izzet Prowess" "Izzet Prowess v2" -f standard -n 2000
mtgasim report
```

Useful options: `-j 6` games at once (default: half your CPU threads), `--vs` to pick opponent decks or folders,
`--seed` to make a run repeatable, `mtgasim setup --ai Hardest` for Forge's strongest (and slowest) AI.

Everything lives in `~/.mtgasim` (decks, gauntlets, results as JSON lines, caches). Set `MTGASIM_HOME` to move it.

## Data sources

* Card names: Arena's own card database on your PC when present, otherwise [Scryfall](https://scryfall.com/docs/api).
* Legality and colour identity: Scryfall.
* Brawl opponent lists: the cards you saw each opponent play, topped up with [EDHREC](https://edhrec.com)'s
  average deck for that commander.

## Licence

MTGASIM is free software under the GNU GPL v3 (see `LICENSE`), because its Java harness links against Forge,
which is GPL v3. The harness source is in `harness/src`.

MTGASIM is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards.
Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
