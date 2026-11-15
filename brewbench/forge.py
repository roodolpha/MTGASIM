"""Finding and preparing Forge (the open-source Magic rules engine) and Java."""
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

FORGE_VERSION = "2.0.16"   # the harness is built and tested against this Forge release
HARNESS_JAR = Path(__file__).resolve().parent / "harness" / "brewbench-harness.jar"   # shipped prebuilt
HARNESS_SRC = Path(__file__).resolve().parent.parent / "harness" / "src"            # source (GPL)

JVM_FLAGS = ["-Xmx1200m", "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=2", "-XX:CICompilerCount=2",
             "-Dfile.encoding=UTF-8", "-Djava.awt.headless=true"]   # one game is one thread


class SetupError(RuntimeError):
    pass


def forge_jar(forge_dir) -> Path:
    jars = sorted(Path(forge_dir).glob("forge-gui-desktop-*-jar-with-dependencies.jar"))
    if not jars:
        raise SetupError(f"No Forge desktop jar in {forge_dir}. Download Forge {FORGE_VERSION} "
                         "(https://github.com/Card-Forge/forge/releases), unpack it, and point "
                         "`brewbench setup --forge-dir` at that folder.")
    return jars[-1]


def forge_version(forge_dir) -> str:
    m = re.search(r"forge-gui-desktop-(.+?)-jar-with-dependencies", forge_jar(forge_dir).name)
    return m.group(1) if m else "?"


def find_java(forge_dir=None, configured=None) -> str:
    """A java executable: configured path, a JRE bundled inside the Forge folder, JAVA_HOME, then PATH."""
    if configured and Path(configured).exists():
        return str(configured)
    exe = "java.exe" if os.name == "nt" else "java"
    if forge_dir:
        for p in Path(forge_dir).glob(f"**/bin/{exe}"):
            return str(p)
    jh = os.environ.get("JAVA_HOME")
    if jh and (Path(jh) / "bin" / exe).exists():
        return str(Path(jh) / "bin" / exe)
    found = shutil.which("java")
    if found:
        return found
    raise SetupError("Java 17 or newer is needed. Install it (e.g. https://adoptium.net) or pass --java.")


def java_major(java) -> int:
    try:
        out = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=30)
        m = re.search(r'version "(\d+)(?:\.(\d+))?', out.stderr + out.stdout)
        if not m:
            return 0
        major = int(m.group(1))
        return int(m.group(2)) if major == 1 else major
    except (OSError, subprocess.SubprocessError):
        return 0


def prepare(forge_dir, ai_profile="Default"):
    """Settings Forge needs for fast headless games: load card scripts only when a deck uses them,
    and pick the AI personality (res/ai/<name>.ai) both players use."""
    d = Path(forge_dir) / "userdata" / "preferences"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "forge.preferences"
    txt = p.read_text(encoding="utf-8") if p.exists() else ""
    want = ["LOAD_CARD_SCRIPTS_LAZILY=true", f"UI_CURRENT_AI_PROFILE={ai_profile}"]
    if any(w not in txt.splitlines() for w in want):
        keep = [l for l in txt.splitlines() if not l.startswith(("LOAD_CARD_SCRIPTS_LAZILY", "UI_CURRENT_AI_PROFILE"))]
        p.write_text("\n".join(keep + want) + "\n", encoding="utf-8")


def ai_profiles(forge_dir) -> list:
    return sorted(p.stem for p in (Path(forge_dir) / "res" / "ai").glob("*.ai"))


def card_names(forge_dir) -> set:
    """Every card name Forge knows, read from its card scripts."""
    folder = Path(forge_dir) / "res" / "cardsfolder"
    out = set()
    pat = re.compile(r"^Name:(.*)$", re.M)
    z = folder / "cardsfolder.zip"
    if z.exists():
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if n.endswith(".txt"):
                    m = pat.search(zf.read(n).decode("utf-8", "ignore"))
                    if m:
                        out.add(m.group(1).strip())
    else:
        for f in folder.glob("**/*.txt"):
            m = pat.search(f.read_text(encoding="utf-8", errors="ignore"))
            if m:
                out.add(m.group(1).strip())
    return out


def ai_flagged(forge_dir) -> set:
    """Cards Forge's own scripts mark as ones its AI can't play properly (AI:RemoveDeck)."""
    folder = Path(forge_dir) / "res" / "cardsfolder"
    out = set()
    z = folder / "cardsfolder.zip"
    if not z.exists():
        return out
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            if not n.endswith(".txt"):
                continue
            t = zf.read(n).decode("utf-8", "ignore")
            if "AI:RemoveDeck:All" in t or "AI:RemoveDeck:Random" in t:
                m = re.search(r"^Name:(.*)$", t, re.M)
                if m:
                    out.add(m.group(1).strip())
    return out


def build_harness(forge_dir, javac=None) -> Path:
    """Compile the Java harness against the user's Forge jar (only needed if the bundled jar doesn't match)."""
    javac = javac or shutil.which("javac")
    if not javac:
        raise SetupError("Building the harness needs a JDK (javac). The bundled harness jar works with "
                         f"Forge {FORGE_VERSION}.")
    import tempfile
    jar = forge_jar(forge_dir)
    with tempfile.TemporaryDirectory() as tmp:
        srcs = [str(p) for p in HARNESS_SRC.glob("**/*.java")]
        subprocess.run([javac, "--release", "17", "-cp", str(jar), "-d", tmp] + srcs, check=True)
        HARNESS_JAR.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(HARNESS_JAR, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in Path(tmp).glob("**/*.class"):
                zf.write(f, f.relative_to(tmp).as_posix())
    return HARNESS_JAR


def command(java, forge_dir, fmt, deck_a, deck_b, games, out, timeout=180, seed=None):
    sep = ";" if os.name == "nt" else ":"
    cp = str(forge_jar(forge_dir)) + sep + str(HARNESS_JAR)
    cmd = [java] + JVM_FLAGS + ["-cp", cp, "brewbench.Sim", fmt.forge, str(deck_a), str(deck_b),
                                str(games), str(out), str(timeout)]
    if seed is not None:
        cmd.append(str(seed))
    return cmd
