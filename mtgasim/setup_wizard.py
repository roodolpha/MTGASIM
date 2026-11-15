"""First-run setup, driven from the dashboard: find Arena's log, download Java and Forge into ~/.mtgasim,
and point the config at them. Also the "is there a newer MTGASIM?" check."""
import json
import os
import platform
import re
import shutil
import tarfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from . import __version__, arena_log, forge

UA = {"User-Agent": f"MTGASIM/{__version__}", "Accept": "application/json"}
FORGE_REPO = "Card-Forge/forge"
APP_REPO = "roodolpha/MTGASIM"
JOBS = {}   # name -> {"state": "running|done|error", "done": bytes, "total": bytes, "error": str}


def _get_json(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url, job, path, timeout=60):
    """Stream to a file (Forge is ~300 MB), updating the job's progress."""
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
        JOBS[job].update(total=int(r.headers.get("Content-Length") or 0))
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            JOBS[job]["done"] = f.tell()
    return path


def _extract(t, dest):
    """Unpack safely (no paths escaping dest) on Pythons that support the filter."""
    try:
        t.extractall(dest, filter="data")
    except TypeError:
        t.extractall(dest)


def status(cfg):
    out = {"version": __version__, "home": str(cfg.home)}
    try:
        fd = cfg.forge_dir
        out["forge"] = {"ok": True, "dir": str(fd), "version": forge.forge_version(fd)}
    except forge.SetupError:
        out["forge"] = {"ok": False}
    try:
        j = forge.find_java(cfg.get("forge_dir"), cfg.get("java"))
        major = forge.java_major(j)
        out["java"] = {"ok": major >= 17, "path": j, "version": major}
    except forge.SetupError:
        out["java"] = {"ok": False}
    logs = arena_log.find_logs(cfg.get("arena_log"))
    out["arena_log"] = {"ok": bool(logs), "path": str(logs[-1]) if logs else None}
    if logs:
        try:   # detailed logs are on if the log mentions the GRE messages we read
            with open(logs[-1], encoding="utf-8", errors="ignore") as f:
                head = f.read(4_000_000)
            out["arena_log"]["detailed"] = "greToClientEvent" in head or "==> " in head
        except OSError:
            pass
    out["decks"] = len(list(cfg.decks_dir.glob("*.dck")))
    out["ready"] = out["forge"]["ok"] and out["java"]["ok"]
    out["jobs"] = JOBS
    return out


# ------------------------------------------------------------------ Java
def _jre_url():
    os_ = {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(platform.system(), "linux")
    arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return f"https://api.adoptium.net/v3/binary/latest/17/ga/{os_}/{arch}/jre/hotspot/normal/eclipse"


def install_java(cfg):
    job = "java"
    JOBS[job] = {"state": "running", "done": 0, "total": 0}
    try:
        arc = _download(_jre_url(), job, cfg.home / "runtime" / "jre.download", timeout=120)
        dest = cfg.home / "runtime" / "jre"
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        if zipfile.is_zipfile(arc):
            with zipfile.ZipFile(arc) as z:
                z.extractall(dest)
        else:
            with tarfile.open(arc) as t:
                _extract(t, dest)
        arc.unlink()
        exe = next(dest.glob("**/bin/java.exe"), None) or next(dest.glob("**/bin/java"), None)
        if not exe:
            raise RuntimeError("downloaded Java, but couldn't find java inside it")
        if os.name != "nt":
            exe.chmod(0o755)
        cfg.set("java", str(exe))
        JOBS[job]["state"] = "done"
    except Exception as e:
        JOBS[job].update(state="error", error=str(e))


# ------------------------------------------------------------------ Forge
def find_forge_asset(version=forge.FORGE_VERSION):
    """The desktop build of Forge `version` from its GitHub releases (falls back to the newest desktop build)."""
    fallback = None
    for page in range(1, 6):
        rels = _get_json(f"https://api.github.com/repos/{FORGE_REPO}/releases?per_page=30&page={page}")
        if not rels:
            break
        for rel in rels:
            for a in rel.get("assets", []):
                n = a["name"]
                # Forge publishes the desktop build as forge-installer-<ver>.tar.bz2 (older: forge-gui-desktop-...)
                if re.match(r"forge-(installer|gui-desktop)-[\d.]+\.tar\.bz2$", n):
                    if version in n:
                        return a["browser_download_url"], n
                    fallback = fallback or (a["browser_download_url"], n)
    if fallback:
        return fallback
    raise RuntimeError("couldn't find a Forge desktop download on GitHub")


def install_forge(cfg):
    job = "forge"
    JOBS[job] = {"state": "running", "done": 0, "total": 0}
    try:
        cfg.home.mkdir(parents=True, exist_ok=True)
        url, name = find_forge_asset()
        JOBS[job]["file"] = name
        arc = _download(url, job, cfg.home / "forge.download", timeout=300)
        JOBS[job]["unpacking"] = True
        dest = cfg.home / "forge"
        tmp = cfg.home / "forge.part"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        with tarfile.open(arc, mode="r:bz2") as t:
            _extract(t, tmp)
        arc.unlink()
        jar = next(tmp.glob("**/forge-gui-desktop-*-jar-with-dependencies.jar"))
        root = jar.parent
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(root), str(dest))
        shutil.rmtree(tmp, ignore_errors=True)
        cfg.set("forge_dir", str(dest))
        if forge.forge_version(dest) != forge.FORGE_VERSION:
            JOBS[job]["warning"] = (f"Got Forge {forge.forge_version(dest)}; the simulator was built for "
                                    f"{forge.FORGE_VERSION}. If games all error, tell us on GitHub.")
        JOBS[job]["state"] = "done"
    except Exception as e:
        JOBS[job].update(state="error", error=str(e))


def start(cfg, what):
    fn = {"java": install_java, "forge": install_forge}[what]
    if JOBS.get(what, {}).get("state") == "running":
        return
    threading.Thread(target=fn, args=(cfg,), daemon=True).start()


def use_existing(cfg, forge_dir=None, java=None, arena_log=None):
    if forge_dir:
        forge.forge_jar(forge_dir)   # raises if it isn't a Forge folder
        cfg.set("forge_dir", str(Path(forge_dir)))
    if java:
        cfg.set("java", java)
    if arena_log:
        cfg.set("arena_log", arena_log)
    return status(cfg)


# ------------------------------------------------------------------ updates
def _vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def check_update():
    try:
        rel = _get_json(f"https://api.github.com/repos/{APP_REPO}/releases/latest", timeout=10)
    except Exception:
        return {"current": __version__, "latest": None}
    latest = (rel.get("tag_name") or "").lstrip("v")
    newer = bool(latest) and _vtuple(latest) > _vtuple(__version__)
    return {"current": __version__, "latest": latest, "newer": newer, "url": rel.get("html_url"),
            "notes": (rel.get("body") or "")[:2000]}
