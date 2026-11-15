import shutil
import tarfile

from brewbench import setup_wizard as S
from brewbench.config import Config


def test_install_forge_unpacks_and_configures(tmp_path, monkeypatch):
    src = tmp_path / "src"
    (src / "res" / "ai").mkdir(parents=True)
    (src / "forge-gui-desktop-2.0.16-jar-with-dependencies.jar").write_bytes(b"jar")
    (src / "res" / "ai" / "Default.ai").write_text("x")
    arc = tmp_path / "forge-installer-2.0.16.tar.bz2"
    with tarfile.open(arc, "w:bz2") as t:
        for p in src.rglob("*"):
            t.add(p, p.relative_to(src).as_posix())
    cfg = Config(tmp_path / "home")
    monkeypatch.setattr(S, "find_forge_asset", lambda version=None: ("http://x", arc.name))
    monkeypatch.setattr(S, "_download", lambda url, job, path, timeout=60: shutil.copyfile(arc, path) or path)
    S.install_forge(cfg)
    assert S.JOBS["forge"]["state"] == "done", S.JOBS["forge"]
    assert (cfg.forge_dir / "forge-gui-desktop-2.0.16-jar-with-dependencies.jar").exists()
    assert (cfg.forge_dir / "res" / "ai" / "Default.ai").exists()
    assert not (cfg.home / "forge.download").exists()


def test_update_check_compares_versions(monkeypatch):
    monkeypatch.setattr(S, "_get_json", lambda url, timeout=30: {"tag_name": "v99.0.0", "html_url": "u", "body": ""})
    assert S.check_update()["newer"] is True
    monkeypatch.setattr(S, "_get_json", lambda url, timeout=30: {"tag_name": "v0.0.1", "html_url": "u", "body": ""})
    assert S.check_update()["newer"] is False
