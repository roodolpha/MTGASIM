# Beta testing Brewbench

Thanks for helping. Brewbench simulates your MTG Arena decks against the decks you actually face, using Forge's AI,
and tracks your real Arena games. Everything runs on your PC.

## Install

1. Download **brewbench-setup.exe** from https://mtgasim.roododger.workers.dev/download/windows
2. Windows may say "Windows protected your PC" because the app isn't signed yet. Click **More info**, then **Run anyway**.
3. In MTG Arena: **Options > Account > Detailed Logs (Plugin Support)** on, then restart Arena. Brewbench only ever
   reads Arena's log file.
4. Open Brewbench. The setup checklist downloads Java and Forge (about 350 MB, once).

**Mac (experimental):** download **brewbench-mac.zip** from the same page, unzip, then right-click
Brewbench > Open the first time (it isn't signed, so macOS asks). There's no menu-bar icon on Mac yet: closing
the window quits, so leave it open while you play if you want games recorded.

## What to try

- **Decks:** your Arena decks should appear on their own. Check the card counts and formats look right.
- **Opponents:** on the Decks page, build opponents from the commanders you've faced, or add some by name.
- **Sims:** pick a deck and run 200 games. Try **Stop sims** part-way through.
- **My games:** play a few Arena games with Brewbench running (it sits in the tray) and check they show up.
- **Sharing** (optional): Settings > Share with Brewbench. Use "See exactly what's sent" first.

## Reporting a problem

Open an issue: https://github.com/roodolpha/MTGASIM/issues/new/choose

Please attach **Settings > Download diagnostics**. It's a zip of logs and settings, and it leaves out your Arena
account and your sharing key. Say what you did, what you expected, and what happened instead.

## Message to send testers

> Hey! I've built a free MTG Arena tool called Brewbench and I'm looking for a handful of people to try it for a
> week before I share it more widely. It plays your deck thousands of times against the decks you actually run
> into (using Forge's AI), so you can tell whether a change really helped, and it tracks your Arena games.
> Everything runs on your own PC.
>
> Download: https://mtgasim.roododger.workers.dev/download/windows
> Quick guide and how to report bugs: https://github.com/roodolpha/MTGASIM/blob/main/docs/BETA.md
>
> It's not signed yet, so Windows will warn about an unknown publisher: More info, then Run anyway.
> Any feedback, even "this bit confused me", is really useful. Thanks!
