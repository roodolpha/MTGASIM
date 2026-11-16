"""Card names and legality. Arena identifies cards by number (grpId); Forge by name.
Names come from Arena's own card database on disk when it's there, else from Scryfall (cached)."""
import glob
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Brewbench/0.1 (+https://github.com/roodolpha/MTGASIM)", "Accept": "application/json"}


def _arena_db_candidates():
    roots = [os.environ.get("ARENA_INSTALL_DIR", "")]
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            roots += [os.path.join(base, "Wizards of the Coast", "MTGA"),
                      os.path.join(base, "Steam", "steamapps", "common", "MTGA"),
                      os.path.join(base, "Epic Games", "MagicTheGathering")]
        for drive in "CDEFG":
            roots += [f"{drive}:\\SteamLibrary\\steamapps\\common\\MTGA"]
        pattern = os.path.join("MTGA_Data", "Downloads", "Raw", "Raw_CardDatabase_*.mtga")
    else:
        roots += [str(Path.home() / "Library" / "Application Support" / "com.wizards.mtga"),
                  "/Applications/MTGA.app/Contents/Resources/Data",
                  str(Path.home() / "Library" / "Application Support" / "Steam" / "steamapps" / "common" / "MTGA")]
        pattern = os.path.join("**", "Raw_CardDatabase_*.mtga")
    found = []
    for r in filter(None, roots):
        found += glob.glob(os.path.join(r, pattern), recursive=True)
    return found


def arena_names() -> dict:
    """{grpId: name} from Arena's SQLite card database, or {} if it can't be found."""
    found = _arena_db_candidates()
    if not found:
        return {}
    path = max(found, key=os.path.getmtime)
    names = {}
    try:
        con = sqlite3.connect(f"file:{urllib.request.pathname2url(path)}?mode=ro", uri=True)
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "Localizations_enUS" in tables:
            q = ("select c.GrpId, l.Loc from Cards c join Localizations_enUS l "
                 "on l.LocId = c.TitleId and l.Formatted = 1")
        else:
            q = "select c.GrpId, l.enUS from Cards c join Localizations l on l.LocId = c.TitleId"
        for grp, name in con.execute(q):
            names.setdefault(int(grp), re.sub(r"<[^>]+>", "", name or "").strip())
        con.close()
    except sqlite3.Error:
        return {}
    return names


def _get(url, data=None, timeout=20):
    headers = dict(UA)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class CardBook:
    """grpId -> name, with a disk cache. Scryfall asks for at most ~10 requests a second."""

    def __init__(self, cache_file):
        self.path = Path(cache_file)
        try:
            self.cache = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}
        self._local = None
        self.dirty = False

    def name(self, grp_id):
        key = str(grp_id)
        if key in self.cache:
            return self.cache[key]
        if self._local is None:
            self._local = arena_names()
        n = self._local.get(int(grp_id))
        if not n:
            try:
                n = _get(f"https://api.scryfall.com/cards/arena/{int(grp_id)}")["name"]
                time.sleep(0.1)
            except Exception:
                return None   # offline or unknown: don't cache, try again next time
        self.cache[key] = n
        self.dirty = True
        return n

    def save(self):
        if self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.cache), encoding="utf-8")
            self.dirty = False


def legality(names, fmt_key, cache_file=None) -> dict:
    """{name: 'legal' | 'not_legal' | 'banned' | ...} for one format, via Scryfall's collection endpoint."""
    cache = {}
    cpath = Path(cache_file) if cache_file else None
    if cpath and cpath.exists():
        try:
            cache = json.loads(cpath.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    want = [n for n in names if n not in cache]
    for i in range(0, len(want), 75):
        chunk = want[i:i + 75]
        try:
            d = _get("https://api.scryfall.com/cards/collection",
                     {"identifiers": [{"name": n} for n in chunk]})
        except Exception:
            break
        for c in d.get("data", []):
            for key in {c["name"], c["name"].split(" // ")[0]}:
                cache[key] = c.get("legalities", {})
        time.sleep(0.1)
    if cpath:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps(cache), encoding="utf-8")
    return {n: (cache.get(n) or {}).get(fmt_key) for n in names if n in cache}


def identity(names, cache_file=None) -> dict:
    """{name: {"ci": colour identity, "colors": colours, "type": type line}} from Scryfall, cached."""
    cache = {}
    cpath = Path(cache_file) if cache_file else None
    if cpath and cpath.exists():
        try:
            cache = json.loads(cpath.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    want = [n for n in dict.fromkeys(names) if n and (n not in cache or "cmc" not in cache[n])]
    for i in range(0, len(want), 75):
        try:
            d = _get("https://api.scryfall.com/cards/collection",
                     {"identifiers": [{"name": n} for n in want[i:i + 75]]})
        except Exception:
            break
        for c in d.get("data", []):
            tl = c.get("type_line") or (c.get("card_faces") or [{}])[0].get("type_line", "")
            cols = c.get("colors")
            if cols is None:
                cols = sorted({x for f in c.get("card_faces") or [] for x in f.get("colors") or []})
            v = {"ci": "".join(c.get("color_identity") or []), "colors": "".join(cols), "type": tl,
                 "cmc": c.get("cmc") or 0}
            cache[c["name"]] = v
            cache.setdefault(c["name"].split(" // ")[0], v)
        time.sleep(0.1)
    if cpath:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps(cache), encoding="utf-8")
    return {n: cache[n] for n in names if n in cache}


WUBRG = "WUBRG"


def colour_string(letters) -> str:
    s = "".join(c for c in WUBRG if c in set(letters))
    return s or "C"


GUILDS = {"W": "Mono-White", "U": "Mono-Blue", "B": "Mono-Black", "R": "Mono-Red", "G": "Mono-Green", "C": "Colourless",
          "WU": "Azorius", "UB": "Dimir", "BR": "Rakdos", "RG": "Gruul", "WG": "Selesnya", "WB": "Orzhov",
          "UR": "Izzet", "BG": "Golgari", "WR": "Boros", "UG": "Simic", "WUB": "Esper", "UBR": "Grixis",
          "BRG": "Jund", "WRG": "Naya", "WUG": "Bant", "WBG": "Abzan", "WUR": "Jeskai", "UBG": "Sultai",
          "WBR": "Mardu", "URG": "Temur", "WUBRG": "Five-colour"}


def archetype(main, ident):
    """A readable name for a constructed deck: its colours plus how fast it is, e.g. "Rakdos Midrange".
    Speed comes from the average mana value of its non-land cards (counting copies)."""
    total = n = 0
    letters = set()
    for name, q in main.items():
        i = ident.get(name)
        if not i or "Land" in i["type"].split(" // ")[0]:
            continue
        letters |= set(i["colors"])
        total += (i.get("cmc") or 0) * q
        n += q
    if not n:
        return None
    avg = total / n
    style = "Aggro" if avg < 2.4 else "Midrange" if avg < 3.3 else "Control"
    return f"{GUILDS.get(colour_string(letters), colour_string(letters))} {style}"
