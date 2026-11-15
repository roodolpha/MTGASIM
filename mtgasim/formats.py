"""The Arena formats MTGASIM can simulate, and what each one means for Forge and for deck checks."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    key: str             # what you type on the command line
    name: str            # what we show
    forge: str           # game type the Java harness runs: "brawl" or "constructed"
    scryfall: str        # Scryfall legality key, used when checking a deck
    deck_size: int       # cards in the main deck (commander excluded)
    singleton: bool      # one copy of each non-basic
    commander: bool      # needs a commander


FORMATS = {
    f.key: f for f in (
        Format("brawl", "Brawl (Historic Brawl)", "brawl", "brawl", 99, True, True),
        Format("standardbrawl", "Standard Brawl", "brawl", "standardbrawl", 59, True, True),
        Format("standard", "Standard", "constructed", "standard", 60, False, False),
        Format("historic", "Historic", "constructed", "historic", 60, False, False),
        Format("timeless", "Timeless", "constructed", "timeless", 60, False, False),
        Format("alchemy", "Alchemy", "constructed", "alchemy", 60, False, False),
    )
}


def get(key: str) -> Format:
    try:
        return FORMATS[key.lower().replace(" ", "").replace("-", "")]
    except KeyError:
        raise ValueError(f"Unknown format {key!r}. Choose one of: {', '.join(FORMATS)}") from None
