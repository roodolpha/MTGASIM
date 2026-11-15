"""Settings and where Brewbench keeps its files (one folder, ~/.brewbench unless BREWBENCH_HOME says otherwise)."""
import json
import os
from pathlib import Path

DEFAULTS = {
    "forge_dir": None,          # folder holding forge-gui-desktop-*-jar-with-dependencies.jar
    "java": None,               # java executable; found automatically when empty
    "ai_profile": "Default",    # Forge AI personality: Default, Cautious, Reckless, Experimental...
    "instances": None,          # parallel games; empty = half your CPU threads
    "arena_log": None,          # Player.log; found automatically when empty
}


def default_home():
    """~/.brewbench, or ~/.mtgasim for people who used the app before it was renamed."""
    new, old = Path.home() / ".brewbench", Path.home() / ".mtgasim"
    return old if old.exists() and not new.exists() else new


class Config:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get("BREWBENCH_HOME") or os.environ.get("MTGASIM_HOME") or default_home())
        self.file = self.home / "config.json"
        self.data = dict(DEFAULTS)
        if self.file.exists():
            try:
                self.data.update(json.loads(self.file.read_text(encoding="utf-8")))
            except ValueError:
                pass

    def get(self, key, default=None):
        v = self.data.get(key)
        return default if v is None else v

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        self.home.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    @property
    def forge_dir(self):
        from .forge import SetupError
        d = self.get("forge_dir")
        if not d or not Path(d).exists():
            raise SetupError("Forge isn't set up yet. Run: brewbench setup --forge-dir <your Forge folder>")
        return Path(d)

    @property
    def decks_dir(self):
        return self.home / "decks"

    def gauntlet_dir(self, fmt_key):
        return self.home / "gauntlets" / fmt_key

    @property
    def results_dir(self):
        return self.home / "results"

    @property
    def cache_dir(self):
        return self.home / "cache"
