# Privacy

*Plain-English version. Last updated: 16 November 2026.*

**Who's responsible:** roodolpha, the developer who runs Brewbench. Contact: ask in the [Brewbench Discord](https://discord.gg/kTnCXydsgC), open an issue at [github.com/roodolpha/MTGASIM/issues](https://github.com/roodolpha/MTGASIM/issues), or for anything you'd rather not post publicly, ask there for a private contact and you'll be given one.

## This website

The site doesn't use cookies, analytics or ads. Its fonts are served from this site. Card images come from Scryfall
(scryfall.com), so your browser asks Scryfall for them and Scryfall sees your IP address, as any website you load
something from does. The site remembers the format you last picked in your browser's storage, and nothing else.

## The app on your PC

The Brewbench app keeps everything on your computer: your decks, simulations, and the record of your Arena games
it reads from Arena's own log file. Nothing leaves your PC unless you choose to share.

It reads Arena's `Player.log` and nothing else from Arena. It doesn't read Arena's memory, change the game, or
send anything to Wizards.

It talks to the internet for: card names, art and legality (Scryfall), downloading Java and Forge the first time,
checking the Brewbench website for a newer version, EDHREC's average decklists when you build opponent decks
(you can untick that), and the sharing below, only if you turn it on.

## Crash reports (off unless you turn them on in Settings)

If you tick "Send crash reports", the app sends a report when something goes wrong: the error message and the
lines of Brewbench's code it came from, which part of the app it was in, your Brewbench and Windows versions, and
a random install number the app makes up (only used to count how many installs hit the same problem). Folder
paths are scrubbed so your user name isn't included. Never any Arena data, decks, games, account or sharing key.
Reports are kept for up to 90 days. Untick it to stop.

## If you share (off unless you turn it on in Settings)

**What we receive:** for each of your real Arena games: the day (not the time), format, result, your deck's
colours or commander, a scrambled fingerprint of your list, the opponent's colours or commander as far as you saw
them, and your rank before the game. Summaries of your simulator runs. Your decklists only if you tick "Share my decklists too".
A random uploader ID and key that your copy of brewbench makes up.

**What we never receive:** your Arena name or account ID, your opponents' names, Arena's match IDs (they're
scrambled with your uploader ID first), your email, your IP address beyond what any web server sees in passing.

**Public or not:** you're anonymous unless you pick a display name *and* tick "Show me on leaderboards". Anonymous games only count
towards the meta and matchup numbers. Public players appear on leaderboards and get a player page.

**Why we hold it (lawful basis):** your consent, given when you press Start sharing. You can withdraw it at any
time.

**Deleting it:** Settings > Share with Brewbench > "Remove everything from the site" (or `brewbench share --forget`) deletes everything your uploader ID sent, straight away. Decklists you
shared aren't linked to you and stay. To ask for anything else, use the contact above.

**Where it lives:** Cloudflare's servers (their D1 database). Backups are kept for up to 30 days.

**Your rights (UK GDPR):** access, correction, deletion, objection and complaint. You can complain to the
Information Commissioner's Office (ico.org.uk).
