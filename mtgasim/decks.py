"""Decklists: read Arena's export text, read and write Forge .dck files, and check a list against a format."""
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
          "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
          "Snow-Covered Mountain", "Snow-Covered Forest"}

# "4 Lightning Strike (M19) 152" / "1 Fable of the Mirror-Breaker" / "2x Opt"
_LINE = re.compile(r"^\s*(\d+)\s*x?\s+(.+?)(?:\s+\(([A-Za-z0-9_]+)\)(?:\s+\S+)?)?\s*$")
_SECTIONS = {"commander": "commander", "deck": "main", "main": "main", "maindeck": "main",
             "sideboard": "side", "companion": "companion", "about": "about"}


def clean_name(name: str) -> str:
    """Forge names double-faced cards by their front face; Arena uses 'Front // Back' or 'Front /// Back'."""
    name = re.sub(r"<[^>]+>", "", name).strip()
    name = re.split(r"\s+//+\s+", name)[0]
    return name.strip()


@dataclass
class Deck:
    name: str = "deck"
    commanders: list = field(default_factory=list)
    main: Counter = field(default_factory=Counter)
    side: Counter = field(default_factory=Counter)

    @property
    def size(self) -> int:
        return sum(self.main.values())

    def all_names(self):
        return set(self.commanders) | set(self.main) | set(self.side)

    def to_dck(self) -> str:
        out = ["[metadata]", f"Name={self.name}"]
        if self.commanders:
            out.append("[Commander]")
            out += [f"1 {c}" for c in self.commanders]
        out.append("[Main]")
        out += [f"{q} {n}" for n, q in self.main.items()]
        if self.side:
            out.append("[Sideboard]")
            out += [f"{q} {n}" for n, q in self.side.items()]
        return "\n".join(out) + "\n"

    def to_arena(self) -> str:
        out = []
        if self.commanders:
            out += ["Commander"] + [f"1 {c}" for c in self.commanders] + [""]
        out += ["Deck"] + [f"{q} {n}" for n, q in self.main.items()]
        if self.side:
            out += ["", "Sideboard"] + [f"{q} {n}" for n, q in self.side.items()]
        return "\n".join(out) + "\n"

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_dck(), encoding="utf-8")
        return path


def parse_arena(text: str, name: str = "deck") -> Deck:
    """Arena's Export button text. Section headers are optional: with none, everything is the main deck,
    and a blank line followed by more cards starts the sideboard (Arena's older export style)."""
    deck = Deck(name=name)
    section, saw_header, blank_after_cards = "main", False, False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if deck.main and not saw_header:
                blank_after_cards = True
            continue
        key = line.lower().rstrip(":").replace(" ", "")
        if key in _SECTIONS:
            section, saw_header = _SECTIONS[key], True
            continue
        if key.startswith("name") and section == "about":
            deck.name = line.split(" ", 1)[1].strip() if " " in line else deck.name
            continue
        m = _LINE.match(line)
        if not m:
            continue
        qty, card = int(m.group(1)), clean_name(m.group(2))
        target = "side" if (blank_after_cards and not saw_header) else section
        if target == "commander":
            deck.commanders.append(card)
        elif target == "side":
            deck.side[card] += qty
        elif target == "companion":
            deck.side[card] += qty
        elif target == "main":
            deck.main[card] += qty
    return deck


def read_dck(path) -> Deck:
    path = Path(path)
    deck = Deck(name=path.stem)
    section = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("["):
            section = line.strip("[]").lower()
            continue
        if section == "metadata":
            if line.lower().startswith("name="):
                deck.name = line.split("=", 1)[1]
            continue
        m = re.match(r"^(\d+)\s+(.+?)(?:\|.*)?$", line)
        if not m:
            continue
        qty, card = int(m.group(1)), clean_name(m.group(2))
        if section == "commander":
            deck.commanders += [card] * qty
        elif section == "main":
            deck.main[card] += qty
        elif section == "sideboard":
            deck.side[card] += qty
    return deck


def load(path_or_text, name=None) -> Deck:
    """A .dck file, an Arena export .txt file, or Arena export text pasted directly."""
    p = Path(path_or_text) if len(str(path_or_text)) < 400 and "\n" not in str(path_or_text) else None
    if p is not None and p.exists():
        if p.suffix.lower() == ".dck":
            return read_dck(p)
        return parse_arena(p.read_text(encoding="utf-8"), name or p.stem)
    return parse_arena(str(path_or_text), name or "deck")


def check(deck: Deck, fmt, known_names=None, legal=None) -> list:
    """Problems that would make a simulation misleading. known_names: what Forge can play.
    legal: {card name: legality string} for this format, when available (from Scryfall)."""
    problems = []
    if fmt.commander and not deck.commanders:
        problems.append(f"{fmt.name} needs a commander: add a 'Commander' section to the list.")
    if deck.size < fmt.deck_size:
        problems.append(f"Main deck has {deck.size} cards; {fmt.name} needs {fmt.deck_size}.")
    if fmt.commander and deck.size > fmt.deck_size:
        problems.append(f"Main deck has {deck.size} cards; {fmt.name} allows {fmt.deck_size}.")
    if fmt.singleton:
        dupes = [n for n, q in deck.main.items() if q > 1 and n not in BASICS]
        if dupes:
            problems.append("More than one copy of: " + ", ".join(sorted(dupes)))
    else:
        over = [n for n, q in deck.main.items() if q > 4 and n not in BASICS]
        if over:
            problems.append("More than four copies of: " + ", ".join(sorted(over)))
    if known_names is not None:
        missing = sorted(n for n in set(deck.commanders) | set(deck.main) if n not in known_names)
        if missing:
            problems.append("Forge doesn't have these cards (they'd be left out): " + ", ".join(missing))
    if legal:
        bad = sorted(n for n in set(deck.commanders) | set(deck.main)
                     if n in legal and legal[n] not in ("legal", "restricted"))
        if bad:
            problems.append(f"Not legal in {fmt.name}: " + ", ".join(bad))
    return problems
