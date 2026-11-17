"""Every page of the app and the website, in a real browser: no JavaScript errors, and the key text is there.
Needs Playwright (pip install playwright && playwright install chromium); skipped otherwise.
Run: pytest tests/browser -q"""
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def wait(port, t=20):
    end = time.time() + t
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close(); return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"nothing on port {port}")


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        exe = os.environ.get("CHROME")
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    (home / "decks").mkdir()
    (home / "decks" / "test-deck.dck").write_text("[metadata]\nName=Test Deck\nFormat=standard\n[Main]\n20 Mountain\n40 Shock\n")
    port = free_port()
    env = dict(os.environ, BREWBENCH_HOME=str(home), BREWBENCH_LATEST_URL="file:///nonexistent")
    p = subprocess.Popen([sys.executable, "-m", "brewbench", "serve", "--port", str(port), "--no-track"],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait(port)
    yield f"http://127.0.0.1:{port}/"
    p.terminate()


@pytest.fixture(scope="module")
def site_url(tmp_path_factory):
    api, web = free_port(), free_port()
    site = tmp_path_factory.mktemp("site")
    for f in (ROOT / "site").iterdir():
        if f.is_file():
            (site / f.name).write_bytes(f.read_bytes())
    cfg = (site / "config.js").read_text()
    (site / "config.js").write_text(re.sub(r'\|\| "https://[^"]+"', f'|| "http://127.0.0.1:{api}"', cfg, count=1))
    procs = [subprocess.Popen([sys.executable, str(Path(__file__).parent / "mock_api.py"), str(api)]),
             subprocess.Popen([sys.executable, str(Path(__file__).parent / "site_server.py"), str(web), str(site)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    wait(api); wait(web)
    yield f"http://127.0.0.1:{web}/"
    for p in procs:
        p.terminate()


def visit(browser, url, expect, width=1440):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    page.wait_for_timeout(1500)
    text = page.inner_text("body")
    wide = page.evaluate("document.documentElement.scrollWidth")
    if wide > width + 2:   # name what sticks out, so a failure says where to look
        print(url, page.evaluate("""(w) => [...document.querySelectorAll('body *')].filter(e => {
            const r = e.getBoundingClientRect(); return r.right > w + 2 && !e.closest('.tablewrap,.scroll'); })
            .slice(0, 8).map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right))""", width))
    page.close()
    assert not errors, f"{url}: {errors}"
    for e in expect:
        assert e in text, f"{url}: expected {e!r}"
    return wide


APP_PAGES = [("#runs", ["Sims"]), ("#decks", ["Decks", "Test Deck", "Opponents"]), ("#settings", ["Settings", "Share with Brewbench"]),
             ("#setup", ["get you simming"]), ("#new", ["New run"]), ("#swap", ["Test a change"]), ("#optimiser", ["Optimiser"]),
             ("tracker", ["My games"])]


@pytest.mark.parametrize("path,expect", APP_PAGES)
def test_app_pages(browser, app_url, path, expect):
    visit(browser, app_url + path, expect)


SITE_PAGES = [("", ["Play your deck", "Commanders on the ladder", "Download for Windows"]), ("meta/brawl", ["Commanders", "Matchups"]),
              ("leaderboard", ["Players"]), ("player/someone", ["Win rate by week"]),
              ("players", ["Players"]), ("how", ["How it works", "Detailed Logs"]), ("api", ["API"]), ("admin.html", ["Admin", "Password"]),
              ("#/meta", ["Commanders", "Matchups"]),       # old-style links still work
              ("no-such-page", ["no page here"])]


@pytest.mark.parametrize("path,expect", SITE_PAGES)
def test_site_pages(browser, site_url, path, expect):
    visit(browser, site_url + path, expect)


@pytest.mark.parametrize("path", ["", "meta/brawl", "leaderboard"])
def test_site_fits_a_phone(browser, site_url, path):
    assert visit(browser, site_url + path, [], width=390) <= 392, "page wider than the phone (see printed elements)"


def test_site_links_change_page_without_reload(browser, site_url):
    page = browser.new_page()
    page.goto(site_url)
    page.wait_for_selector("text=Commanders on the ladder")
    page.evaluate("window.__stay = 1")
    page.click("nav.main >> text=How it works")
    page.wait_for_selector("text=Detailed Logs")
    assert page.url.endswith("/how") and page.evaluate("window.__stay") == 1
    assert page.title() == "How it works | Brewbench"
    page.go_back()
    page.wait_for_selector("text=Commanders on the ladder")
    page.close()
