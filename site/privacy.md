# Privacy

*Plain-English version. Last updated: [DATE OF LAUNCH].*

**Who's responsible:** [YOUR NAME OR TRADING NAME], who runs brewbench. Contact: [CONTACT EMAIL].

## The app on your PC

The brewbench app keeps everything on your computer: your decks, simulations, and the record of your Arena games
it reads from Arena's own log file. Nothing leaves your PC unless you choose to share.

It reads Arena's `Player.log` and nothing else from Arena. It doesn't read Arena's memory, change the game, or
send anything to Wizards.

It talks to the internet for: card names and legality (Scryfall), downloading Java and Forge the first time,
checking GitHub for a newer version, and, only if you turn it on, EDHREC's average decklists.

## If you share (`brewbench share`, off unless you run it)

**What we receive:** for each of your real Arena games: the day (not the time), format, result, your deck's
colours or commander, a scrambled fingerprint of your list, the opponent's colours or commander as far as you saw
them, and your rank before the game. Summaries of your simulator runs. Your decklists only if you pass `--lists`.
A random uploader ID and key that your copy of brewbench makes up.

**What we never receive:** your Arena name or account ID, your opponents' names, Arena's match IDs (they're
scrambled with your uploader ID first), your email, your IP address beyond what any web server sees in passing.

**Public or not:** you're anonymous unless you pick a display name *and* `--public`. Anonymous games only count
towards the meta and matchup numbers. Public players appear on leaderboards and get a player page.

**Why we hold it (lawful basis):** your consent, given when you run `brewbench share`. You can withdraw it at any
time.

**Deleting it:** `brewbench share --forget` deletes everything your uploader ID sent, straight away. Decklists you
shared aren't linked to you and stay. To ask for anything else, email [CONTACT EMAIL].

**Where it lives:** Cloudflare's servers (their D1 database). Backups are kept for up to 30 days.

**Your rights (UK GDPR):** access, correction, deletion, objection and complaint. You can complain to the
Information Commissioner's Office (ico.org.uk).
