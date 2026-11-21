// Brewbench public site: plain JS, reads the public API, no build step.
const API = window.Brewbench_API;
const DISCORD = "https://discord.gg/kTnCXydsgC";
const FORMATS = [["brawl", "Historic Brawl"], ["standardbrawl", "Standard Brawl"], ["standard", "Standard"], ["historic", "Historic"], ["timeless", "Timeless"], ["alchemy", "Alchemy"]];
const NAMES = { W: "Mono-White", U: "Mono-Blue", B: "Mono-Black", R: "Mono-Red", G: "Mono-Green", C: "Colourless",
  WU: "Azorius", UB: "Dimir", BR: "Rakdos", RG: "Gruul", WG: "Selesnya", GW: "Selesnya", WB: "Orzhov", UR: "Izzet", BG: "Golgari", WR: "Boros", RW: "Boros", UG: "Simic", GU: "Simic",
  WUB: "Esper", UBR: "Grixis", BRG: "Jund", WRG: "Naya", WUG: "Bant", WBG: "Abzan", URW: "Jeskai", WUR: "Jeskai", BGU: "Sultai", UBG: "Sultai", WBR: "Mardu", URG: "Temur",
  WUBRG: "Five-colour" };
// the Test a change result shown on the home page: a real run from the developer's Zimone deck
const PROOF = { deck: "Zimone, Paradox Sculptor", out: "Swan Song", in: "Simic Ascendancy", from: 0.536, to: 0.566, games: 2500 };

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pc = (x) => (x == null ? "–" : Math.round(100 * x) + "%");
const pc1 = (x) => (x == null ? "–" : (100 * x).toFixed(1) + "%");
const num = (n) => Number(n || 0).toLocaleString("en-GB");
const games = (n) => `${num(n)} game${n === 1 ? "" : "s"}`;
const isBrawl = (f) => f.endsWith("brawl");
const fmtName = (f) => (FORMATS.find((x) => x[0] === f) || [f, f])[1];
const label = (deck, f) => (isBrawl(f) ? deck : NAMES[deck] || deck);
const range = (r) => (r && r.ci95 ? `${Math.round(100 * Math.max(0, r.ci95[0]))}–${Math.round(100 * Math.min(1, r.ci95[1]))}%` : "");
const mana = (c) => {
  const s = String(c || "").toUpperCase().replace(/[^WUBRGC]/g, "");
  return s ? `<span class="mana" role="img" aria-label="${esc(s.split("").map((x) => ({ W: "white", U: "blue", B: "black", R: "red", G: "green", C: "colourless" }[x])).join(", "))}">${s.split("").map((x) => `<svg><use href="/img/mana.svg#m-${x.toLowerCase()}"/></svg>`).join("")}</span>` : "";
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso) => { const d = new Date(iso + "T12:00:00Z"); return isNaN(d) ? iso : `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`; };
const span = (a, b) => (a === b ? day(a) : `${day(a)} to ${day(b)}`);
// the Monday a week starts on: "2026-W45" is an ISO week; "2026-45" is SQLite's %W (week 1 starts on the year's first Monday)
const weekStart = (w) => {
  const m = /^(\d{4})-(W?)(\d{1,2})$/.exec(w || ""); if (!m) return null;
  const y = +m[1], n = +m[3];
  if (m[2]) { const jan4 = new Date(Date.UTC(y, 0, 4)); return new Date(Date.UTC(y, 0, 4 - ((jan4.getUTCDay() + 6) % 7) + (n - 1) * 7)); }
  const jan1 = new Date(Date.UTC(y, 0, 1)), firstMon = 1 + ((8 - jan1.getUTCDay()) % 7);
  return new Date(Date.UTC(y, 0, Math.max(1, firstMon + (n - 1) * 7)));
};

// ------------------------------------------------------------------ card images (Scryfall, looked up in batches)
const CARDS = {};
try { Object.assign(CARDS, JSON.parse(sessionStorage.getItem("cards") || "{}")); } catch (e) {}
async function loadCards(names) {
  const want = [...new Set(names.filter((n) => n && !(n.toLowerCase() in CARDS)))];
  for (let i = 0; i < want.length; i += 75) {
    const chunk = want.slice(i, i + 75);
    try {
      const r = await fetch("https://api.scryfall.com/cards/collection", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifiers: chunk.map((name) => ({ name })) }) });
      const d = await r.json();
      for (const c of d.data || []) {
        const face = c.image_uris ? c : (c.card_faces || [])[0] || {};
        const img = face.image_uris || {};
        const info = { img: img.normal, small: img.small, art: img.art_crop, artist: face.artist || c.artist };
        CARDS[c.name.toLowerCase()] = info;
        for (const f of c.card_faces || []) CARDS[f.name.toLowerCase()] = CARDS[f.name.toLowerCase()] || info;
      }
      for (const n of chunk) if (!(n.toLowerCase() in CARDS)) CARDS[n.toLowerCase()] = null;
    } catch (e) { /* no images is fine: names still show */ }
  }
  try { sessionStorage.setItem("cards", JSON.stringify(CARDS)); } catch (e) {}
}
const card = (n) => (n && CARDS[n.toLowerCase()]) || null;
// small (146px) or normal (488px) Scryfall image, whichever the shown size needs
const imgTag = (c, alt) => `<img class="cardimg" src="${esc(c.img)}"${c.small ? ` srcset="${esc(c.small)} 146w, ${esc(c.img)} 488w" sizes="(max-width:640px) 44vw, 210px"` : ""} alt="${esc(alt)}" loading="lazy" width="488" height="680">`;
const cardImg = (name, alt = name) => {
  const c = card(name);
  return c && c.img ? imgTag(c, alt) : `<div class="cardimg ph" role="img" aria-label="${esc(alt)}" data-ph="${esc(name)}">${esc(name)}</div>`;
};
const artStyle = (name) => { const c = card(name); return c && c.art ? `background-image:url('${esc(c.art)}')` : ""; };
// pages draw straight away; card images fill in when Scryfall answers
function paintCards() {
  document.querySelectorAll("[data-ph]").forEach((el) => { const c = card(el.dataset.ph); if (c && c.img) el.outerHTML = imgTag(c, el.getAttribute("aria-label")); });
  document.querySelectorAll("[data-art]").forEach((el) => { const c = card(el.dataset.art); if (c && c.art && !el.style.backgroundImage) el.style.backgroundImage = `url('${c.art}')`; });
  const b = document.querySelector(".banner[data-art]"), c = b && card(b.dataset.art);
  if (c && c.artist && !b.querySelector(".credit")) b.insertAdjacentHTML("beforeend", `<span class="credit">Art by ${esc(c.artist)}</span>`);
}
const withCards = (names) => { loadCards(names.filter(Boolean)).then(paintCards); };
// a small art crop for Brawl commanders, mana symbols for constructed archetypes
const deckCell = (deck, colours, f, href) => {
  const nm = esc(label(deck, f));
  const name = href ? `<a href="${href}" class="nm" data-card="${esc(isBrawl(f) ? deck : "")}">${nm}</a>` : `<span class="nm" data-card="${esc(isBrawl(f) ? deck : "")}">${nm}</span>`;
  return `<div class="deck">${isBrawl(f) ? `<span class="art" data-art="${esc(deck)}" style="${artStyle(deck)}"></span>` : ""}<div>${name}${isBrawl(f) ? "" : " " + mana(colours || deck)}</div></div>`;
};

async function get(path) {
  const r = await fetch(API + path);
  if (!r.ok) { const e = new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`); e.status = r.status; throw e; }
  return r.json();
}

// ------------------------------------------------------------------ download button, per system
const OS = /iPhone|iPad|Android|Mobile/i.test(navigator.userAgent) ? "phone" : /Mac/i.test(navigator.platform || navigator.userAgent) ? "mac" : "windows";
function downloadButtons() {
  if (OS === "phone") return `<button class="btn gold" type="button" id="copylink">Copy the link for your PC</button>
    <span class="muted">Brewbench runs on Windows and Mac, not phones.</span>`;
  if (OS === "mac") return `<a class="btn gold" href="/download/mac">Download for Mac (beta)</a><a class="btn" href="/download/windows">Windows</a>`;
  return `<a class="btn gold" href="/download/windows">Download for Windows</a><a class="btn" href="/download/mac">Mac (beta)</a>`;
}
function bindDownload() {
  const b = $("#copylink");
  if (b) b.onclick = async () => { try { await navigator.clipboard.writeText(location.origin + "/"); b.textContent = "Link copied"; } catch (e) { b.textContent = location.host; } };
}

// ------------------------------------------------------------------ format, kept in the address
let FMT = "brawl";
try { FMT = localStorage.getItem("fmt") || "brawl"; } catch (e) {}
function setFmt(f) { if (FORMATS.some((x) => x[0] === f)) { FMT = f; try { localStorage.setItem("fmt", f); } catch (e) {} } }
const fmtPicker = (base) => `<label class="fmt">Format <select id="fmt">${FORMATS.map(([k, n]) => `<option value="${k}"${k === FMT ? " selected" : ""}>${n}</option>`).join("")}</select></label>`;
function bindFmt(base) { const s = $("#fmt"); if (s) s.onchange = () => { setFmt(s.value); go(`/${base === "home" ? "home" : base}/${s.value}`); }; }

function title(t) { document.title = t ? `${t} | Brewbench` : "Brewbench: play your Arena deck before you craft"; }

// card image preview when hovering a commander name
let PREV;
document.addEventListener("mouseover", (e) => {
  const t = e.target.closest && e.target.closest("[data-card]");
  const c = t && card(t.dataset.card);
  if (!c || !c.img || matchMedia("(hover:none)").matches) { if (PREV) PREV.remove(), (PREV = null); return; }
  if (!PREV) { PREV = document.createElement("img"); PREV.className = "preview"; PREV.alt = ""; document.body.appendChild(PREV); }
  PREV.src = c.img;
  const r = t.getBoundingClientRect(), left = r.right + 260 < innerWidth ? r.right + 16 : r.left - 260;
  PREV.style.left = Math.max(8, left) + "px"; PREV.style.top = Math.max(8, Math.min(innerHeight - 350, r.top - 120)) + "px";
});

// ------------------------------------------------------------------ pages
async function home() {
  title("");
  const [meta, lb] = await Promise.all([get(`/v1/meta?format=${FMT}`), get(`/v1/leaderboard?format=${FMT}&min=20`).catch(() => ({ players: [] }))]);
  const decks = meta.decks.filter((d) => d.real && d.real.games > 0);
  const sharing = lb.players.length;
  $("#app").innerHTML = `
  <section class="hero">
    <div>
      <h1>Play your deck a few thousand times before you craft the upgrade.</h1>
      <p class="lede">Brewbench plays your MTG Arena deck against the commanders and decks you actually meet on ladder, on your own PC. Swap a card, run both versions on the same shuffles, and see if it really helped.</p>
      <div class="actions">${downloadButtons()}</div>
      <p class="fine">Free and open source. It only reads Arena's log file and never touches the game. Sims run on your PC only when you start one. <a href="/how">How it works</a></p>
    </div>
    <div class="swap" aria-label="A real Test a change result">
      <div class="pair">
        <figure class="out">${cardImg(PROOF.out)}<figcaption>Took out ${esc(PROOF.out)}</figcaption></figure>
        <figure class="in">${cardImg(PROOF.in)}<figcaption>Put in ${esc(PROOF.in)}</figcaption></figure>
      </div>
      <div class="result"><b class="was">${pc1(PROOF.from)}</b><span>became</span><b>${pc1(PROOF.to)}</b></div>
      <p class="note">Zimone, Paradox Sculptor in Historic Brawl, ${num(PROOF.games)} games for each version.</p>
    </div>
  </section>
  <section class="block">
    <header><div><h2>${isBrawl(FMT) ? "Commanders" : "Decks"} on the ladder</h2></div>${fmtPicker("home")}</header>
    ${decks.length ? `<div class="cards">${decks.slice(0, 11).map((d) => `<a href="/meta/${FMT}">
        ${isBrawl(FMT) ? cardImg(d.deck) : `<div class="cardimg ph" style="${archetypeBg(d.colours || d.deck)}">${mana(d.colours || d.deck)}</div>`}
        <div class="nm">${esc(label(d.deck, FMT))}</div>
        <div class="st"><b>${pc(d.real.win_rate)}</b> won on ladder${d.sim ? `, <span class="sim">${pc(d.sim.win_rate)}</span> in the sim` : ""}<br>${games(d.real.games)}</div></a>`).join("")}
        <div class="invite"><strong>Your deck here</strong>Turn on sharing in the app and your games count towards these numbers. Your name stays private unless you choose otherwise.</div></div>
      <p class="note">${num(meta.real_games)} ladder games in the last 30 days, shared by ${sharing === 1 ? "one player" : sharing ? num(sharing) + " players" : "players"} so far. The more people share, the more this tells you.</p>`
    : `<p class="empty">Nobody has shared ${esc(fmtName(FMT))} games yet. Play ${esc(fmtName(FMT))} with sharing turned on in the app and your decks will be the first here.</p>`}
  </section>
  ${lb.players.length ? `<section class="block"><header><h2>Players</h2><a href="/players/${FMT}">Full table</a></header>${playerTable(lb.players.slice(0, 6), FMT, true)}</section>` : ""}
  <section class="block"><header><div><h2>Questions, bugs, results?</h2><p>The Discord is where updates land first and where to ask if a number looks wrong.</p></div><a class="btn" href="${DISCORD}" rel="noopener">Join the Discord</a></header></section>`;
  bindFmt("home"); bindDownload();
  withCards([PROOF.out, PROOF.in, ...(isBrawl(FMT) ? [...decks.slice(0, 11).map((d) => d.deck), ...lb.players.slice(0, 6).map((p) => p.main_deck)] : [])]);
}

function archetypeBg(c) {
  const v = { W: "#EDE6C8", U: "#3F7FC4", B: "#5D5552", R: "#C9553D", G: "#4F8F5B", C: "#9C958D" };
  const cs = String(c || "C").replace(/[^WUBRGC]/g, "").split("");
  return `background:linear-gradient(160deg,${cs.map((x) => v[x] || v.C).join(",")});align-items:center;justify-content:center`;
}

function playerTable(rows, f, compact) {
  if (!rows.length) return '<p class="empty">Nobody public with enough games yet.</p>';
  return `<div class="tablewrap" tabindex="0" role="region" aria-label="Table, scrolls sideways on small screens"><table><thead><tr><th class="n">#</th><th>Player</th><th class="opt">Main deck</th><th class="n">Won</th><th class="opt">Likely true rate</th><th class="n">Games</th></tr></thead><tbody>${rows.map((r) => `<tr>
   <td class="rank n">${r.pos}</td>
   <td><a href="/player/${encodeURIComponent(r.name)}">${esc(r.name)}</a></td>
   <td class="opt">${deckCell(r.main_deck, r.colours, f)}</td>
   <td class="n">${pc(r.win_rate)}</td><td class="opt range">${range(r)}</td>
   <td class="n">${num(r.games)}</td></tr>`).join("")}</tbody></table></div>`;
}

async function players(m) {
  if (m && m[1]) setFmt(m[1]);
  title(`Players, ${fmtName(FMT)}`);
  const lb = await get(`/v1/leaderboard?format=${FMT}`);
  $("#app").innerHTML = `<div class="pagehead"><h1>Players</h1>
    <p>People who chose to show their name, ${esc(lb.min_rank || "Platinum")} and up, with at least ${num(lb.min_games)} games in the last 30 days. Counted from each player's own Arena log.</p></div>
    <div class="search"><form id="f" style="display:contents"><input id="q" aria-label="Find a player by name" placeholder="Find a player by name" autocomplete="off"><button class="btn" type="submit">Find</button></form>${fmtPicker("players")}</div>
    <div id="lb">${playerTable(lb.players, FMT)}</div>`;
  const q = $("#q");
  q.oninput = () => { const s = q.value.trim().toLowerCase(); $("#lb").innerHTML = playerTable(lb.players.filter((p) => p.name.toLowerCase().includes(s)), FMT); };
  $("#f").onsubmit = (e) => { e.preventDefault(); if (q.value.trim()) go("/player/" + encodeURIComponent(q.value.trim())); };
  bindFmt("players");
  if (isBrawl(FMT)) withCards(lb.players.map((p) => p.main_deck));
}

async function metaPage(m) {
  if (m && m[1]) setFmt(m[1]);
  title(`${isBrawl(FMT) ? "Commanders" : "Decks"}, ${fmtName(FMT)}`);
  const [meta, mx] = await Promise.all([get(`/v1/meta?format=${FMT}`), get(`/v1/matchups?format=${FMT}&top=10`).catch(() => ({ decks: [], grid: [] }))]);
  const decks = meta.decks.filter((d) => d.real && d.real.games > 0);
  const simOnly = meta.decks.filter((d) => !(d.real && d.real.games > 0) && d.sim);
  $("#app").innerHTML = `<div class="pagehead"><h1>${isBrawl(FMT) ? "Commanders" : "Decks"}</h1>
    <p>Ladder results are real games people shared in the last 30 days. Sim results are Forge's AI playing the same decks thousands of times. The likely true rate is where the real win rate probably sits, given how many games there are.</p></div>
  ${fmtPicker("meta")}
  <section class="block" style="border-top:0;padding-top:24px">
    ${decks.length ? `<div class="tablewrap" tabindex="0" role="region" aria-label="Table, scrolls sideways on small screens"><table><thead><tr><th class="n">#</th><th>${isBrawl(FMT) ? "Commander" : "Deck"}</th><th class="n">Won on ladder</th><th class="opt">Likely true rate</th><th class="n">Sim</th><th class="n">Games</th><th class="n opt">Share of games</th></tr></thead><tbody>
    ${decks.map((d, i) => `<tr><td class="rank n">${i + 1}</td><td>${deckCell(d.deck, d.colours, FMT)}</td>
      <td class="n">${d.real.games < 20 ? `<span class="thin" title="Under 20 games">${pc(d.real.win_rate)}</span>` : pc(d.real.win_rate)}</td>
      <td class="opt range">${range(d.real)}</td>
      <td class="n sim">${d.sim ? pc(d.sim.win_rate) : "–"}</td>
      <td class="n">${num(d.real.games)}${d.sim ? `<div class="small">${num(d.sim.games)} simmed</div>` : ""}</td>
      <td class="n opt">${pc1(d.share)}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">${num(meta.real_games)} ladder games. Percentages in italics come from fewer than 20 games, so treat them as a rough guide.${simOnly.length ? ` Not listed: ${simOnly.length} deck${simOnly.length === 1 ? "" : "s"} that so far only exist in simulations.` : ""}</p>`
    : `<p class="empty">Nobody has shared ${esc(fmtName(FMT))} games yet. Play ${esc(fmtName(FMT))} with sharing turned on in the app and your decks will be the first here.</p>`}
  </section>
  ${mx.decks.length > 1 ? `<section class="block"><header><div><h2>Matchups</h2><p>${isBrawl(FMT) ? "Pick a commander to see how it does against the ones it meets most." : "Row deck's win rate against the column deck. Striped cells have too few games to trust."}</p></div>
    ${isBrawl(FMT) ? `<label class="fmt">Commander <select id="who">${mx.decks.map((d, i) => `<option value="${i}">${esc(d)}</option>`).join("")}</select></label>` : ""}</header>
    <div id="mx"></div></section>` : ""}`;
  bindFmt("meta");
  if (isBrawl(FMT)) withCards([...decks.map((d) => d.deck), ...mx.decks]);
  if (mx.decks.length > 1) {
    if (isBrawl(FMT)) {
      const draw = (i) => {
        const rows = mx.grid[i].map((c, j) => ({ j, c, v: c.sim && c.sim.games >= 50 ? c.sim : c.real, src: c.sim && c.sim.games >= 50 ? "sim" : "ladder" }))
          .filter((x) => x.j !== i && x.v).sort((a, b) => b.v.win_rate - a.v.win_rate);
        $("#mx").innerHTML = rows.length ? `<div class="vs">${rows.map((x) => `<div class="row ${x.v.win_rate >= 0.53 ? "w" : x.v.win_rate <= 0.47 ? "l" : ""}">
          <span class="art" data-art="${esc(mx.decks[x.j])}" style="${artStyle(mx.decks[x.j])}"></span>
          <div class="who"><b data-card="${esc(mx.decks[x.j])}">${esc(mx.decks[x.j])}</b><span class="small">${x.src === "sim" ? `<span class="sim">sim</span>` : "ladder"}, ${games(x.v.games)}</span></div>
          <span class="pc${x.src === "sim" ? " sim" : ""}${x.v.games < 20 ? " thin" : ""}">${pc(x.v.win_rate)}</span></div>`).join("")}</div>`
          : '<p class="empty">No matchup results for this commander yet.</p>';
      };
      $("#who").onchange = (e) => { draw(+e.target.value); paintCards(); }; draw(0);
    } else {
      const shade = (v) => { const d = Math.max(-1, Math.min(1, (v - 0.5) / 0.15)); return `background:${d >= 0 ? `rgba(108,195,160,${(Math.abs(d) * 0.55 + 0.1).toFixed(2)})` : `rgba(229,138,110,${(Math.abs(d) * 0.55 + 0.1).toFixed(2)})`}`; };
      $("#mx").innerHTML = `<div class="tablewrap" tabindex="0" role="region" aria-label="Table, scrolls sideways on small screens"><table class="mx"><caption class="small" style="text-align:left;padding:10px 14px">Win rate of the row deck against the column deck</caption><thead><tr><th></th>${mx.decks.map((d) => `<th scope="col">${esc(label(d, FMT))}</th>`).join("")}</tr></thead><tbody>
      ${mx.decks.map((a, i) => `<tr><th scope="row" style="white-space:nowrap">${esc(label(a, FMT))}</th>${mx.grid[i].map((c, j) => {
        if (i === j) return `<td class="few">–</td>`;
        const v = c.sim && c.sim.games >= 50 ? c.sim : c.real;
        if (!v || v.games < 20) return `<td class="few">${v ? pc(v.win_rate) : ""}<small>${v ? games(v.games) : "no games"}</small></td>`;
        return `<td style="${shade(v.win_rate)}">${pc(v.win_rate)}<small>${num(v.games)}${c.sim && c.sim.games >= 50 ? " sim" : ""}</small></td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
  }
}

async function playerPage(m) {
  const name = decodeURIComponent(m[1]);
  title(name);
  let p;
  try { p = await get(`/v1/players/${encodeURIComponent(name)}`); } catch (e) {
    if (e.status !== 404) throw e;
    $("#app").innerHTML = `<div class="pagehead"><h1>No public player called ${esc(name)}</h1><p>Names are exact, and players who share anonymously don't have a page. <a href="/players">See everyone who's public</a>.</p></div>`; return;
  }
  // one row per commander (or colours) and format, however many versions of the list
  const groups = {};
  for (const d of p.decks || []) {
    const k = (d.format || "") + "|" + (d.commander || d.colours);
    const g = groups[k] || (groups[k] = { ...d, versions: 0, games: 0, wins: 0 });
    g.versions++; g.games += d.games; g.wins += d.win_rate * d.games;
    if (d.first < g.first) g.first = d.first; if (d.last > g.last) g.last = d.last;
  }
  const decks = Object.values(groups).map((g) => ({ ...g, win_rate: g.wins / g.games })).sort((a, b) => b.games - a.games);
  const main = decks[0];
  const w = p.weeks || [], W = 640, H = 220, L = 44, R = 30, T = 14, B = 34, lo = 0.25, hi = 0.75;
  const x = (i) => L + (i * (W - L - R)) / Math.max(1, w.length - 1), y = (v) => T + ((hi - Math.max(lo, Math.min(hi, v))) / (hi - lo)) * (H - T - B);
  const now = new Date(), thisWeek = w.length && weekStart(w[w.length - 1].week) && now - weekStart(w[w.length - 1].week) < 7 * 864e5;
  const pts = w.map((v, i) => [x(i), y(v.win_rate)]);
  const solid = thisWeek ? pts.slice(0, -1) : pts;
  const chart = w.length > 1 ? `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Win rate by week">
    ${[0.3, 0.4, 0.5, 0.6, 0.7].map((g) => `<line x1="${L}" x2="${W - R}" y1="${y(g)}" y2="${y(g)}" stroke="${g === 0.5 ? "#4A5677" : "#273149"}"/><text x="${L - 8}" y="${y(g) + 4}" text-anchor="end">${g * 100}%</text>`).join("")}
    ${w.map((v, i) => (i % Math.ceil(w.length / 6) === 0 || i === w.length - 1) && weekStart(v.week) ? `<text x="${x(i)}" y="${H - 10}" text-anchor="middle">${day(weekStart(v.week).toISOString().slice(0, 10))}</text>` : "").join("")}
    <polyline fill="none" stroke="#D9B66A" stroke-width="2.5" points="${solid.map((q) => q.join(",")).join(" ")}"/>
    ${thisWeek && pts.length > 1 ? `<polyline fill="none" stroke="#D9B66A" stroke-width="2" stroke-dasharray="4 5" points="${pts.slice(-2).map((q) => q.join(",")).join(" ")}"/>` : ""}
    ${w.map((v, i) => `<circle cx="${x(i)}" cy="${y(v.win_rate)}" r="4" fill="#D9B66A"><title>Week of ${weekStart(v.week) ? day(weekStart(v.week).toISOString().slice(0, 10)) : esc(v.week)}: ${pc(v.win_rate)} over ${games(v.games)}</title></circle>`).join("")}</svg>
    <ul class="small" style="margin:10px 0 0;padding-left:18px">${w.map((v) => `<li>Week of ${weekStart(v.week) ? day(weekStart(v.week).toISOString().slice(0, 10)) : esc(v.week)}: ${pc(v.win_rate)} over ${games(v.games)}</li>`).join("")}</ul>
    ${thisWeek ? `<p class="note">The dashed part is this week, which isn't finished.</p>` : ""}`
    : `<p class="empty">The chart appears after a couple of weeks of games.</p>`;
  const mc = main && main.commander, credit = mc && card(mc) && card(mc).artist;
  $("#app").innerHTML = `
  <div class="banner"${mc ? ` data-art="${esc(mc)}"` : ""} style="${mc ? artStyle(mc) : ""}"><div><h1>${esc(p.name)}</h1>
    <p>${games(p.games)} shared, ${pc(p.win_rate)} won${main ? `, mostly ${esc(label(main.commander || main.colours, main.format))}` : ""}.</p></div>
    ${credit ? `<span class="credit">Art by ${esc(credit)}</span>` : ""}</div>
  <div class="two" style="margin-top:32px">
    <section><h2 style="margin-bottom:14px">Win rate by week</h2>${chart}</section>
    <section><h2 style="margin-bottom:14px">Decks</h2><div class="tablewrap" tabindex="0" role="region" aria-label="Table, scrolls sideways on small screens"><table><tbody>${decks.map((d) => `<tr><td>${deckCell(d.commander || d.colours, d.colours, d.format || "brawl")}
      <div class="small">${esc(fmtName(d.format))}, ${span(d.first, d.last)}${d.versions > 1 ? `, ${d.versions} versions of the list` : ""}</div></td>
      <td class="n">${pc(d.win_rate)}<div class="small">${games(d.games)}</div></td></tr>`).join("")}</tbody></table></div></section>
  </div>
  <section class="block" style="margin-top:40px"><header><h2>Against</h2><p>Opponents met at least five times.</p></header>
    ${(p.opponents || []).length ? `<div class="vs">${p.opponents.map((o) => `<div class="row ${o.win_rate >= 0.53 ? "w" : o.win_rate <= 0.47 ? "l" : ""}"><span class="art" data-art="${esc(o.opponent)}" style="${artStyle(o.opponent)}"></span>
      <div class="who"><b data-card="${esc(o.opponent)}">${esc(o.opponent)}</b><span class="small">${games(o.games)}</span></div><span class="pc${o.games < 20 ? " thin" : ""}">${pc(o.win_rate)}</span></div>`).join("")}</div>`
      : '<p class="empty">Not enough games against any one opponent yet.</p>'}
  </section>`;
  withCards([...decks.map((d) => d.commander), ...(p.opponents || []).map((o) => o.opponent)]);
}

function howPage() {
  title("How it works");
  $("#app").innerHTML = `<div class="pagehead"><h1>How it works</h1><p>Brewbench is an app for your PC. It reads your decks from Arena, builds opponents from the decks you've actually played against, and has Forge's AI play them against each other thousands of times.</p></div>
  <ol class="steps">
    <li><h2 class="step">Install it</h2><p>${OS === "mac" ? `<a href="/download/mac">Download the Mac beta</a>. It isn't signed yet, so the first time, right-click the app and choose Open.` : `<a href="/download/windows">Download the installer</a> and run it. Until the app is code-signed, Windows may say it's from an unknown publisher: choose More info, then Run anyway.`} The first time it opens, it fetches Java and Forge by itself, which takes a few minutes.</p></li>
    <li><h2 class="step">Tick one setting in Arena</h2><p>Options, then Account, then Detailed Logs (Plugin Support), then restart Arena. Without it, Arena doesn't write your decks or games to its log, so there's nothing for Brewbench to read. You can still paste a deck from Arena's Export button.</p></li>
    <li><h2 class="step">Your decks and opponents appear</h2><p>Brewbench imports your Arena decks, and builds an opponent for each commander or archetype you've faced, weighted by how often you meet them.</p></li>
    <li><h2 class="step">Test a change</h2><p>Swap a card and both versions play the same games: same shuffles, same opponents. If one does better, it's the cards, not luck. If the gap is too small to trust, it says so.</p></li>
    <li><h2 class="step">Share, if you like</h2><p>Sharing is off until you turn it on. Shared games feed the numbers on this site. You're anonymous unless you pick a name. <a href="/privacy">What's sent</a></p></li>
  </ol>
  <section class="block" style="margin-top:48px"><h2 style="margin-bottom:14px">What it can't do</h2><div class="prose">
    <p>Forge's AI plays well but not perfectly, and it misplays some cards. Trust comparisons ("this version beats that one") more than single numbers ("this is a 57% deck").</p>
    <p>Most Alchemy rebalanced cards aren't in Forge, so Alchemy decks may run with cards missing. The app tells you which ones.</p>
    <p>It gives no advice during games and never touches Arena itself. It only reads the log file Arena writes.</p></div></section>
  <section class="block"><h2 style="margin-bottom:14px">What it does to your PC</h2><div class="prose">
    <p>Simulating thousands of games is hard work, so while a sim runs your fans may spin up. That only happens when you start one. Brewbench never runs sims in the background on its own.</p>
    <p>By default it uses half your CPU threads, at low priority so everything else comes first. The app shows how many it's using, and Stop ends every sim straight away. If MTG Arena is open, it slows to one game at a time so your games stay smooth (you can pause it or keep full speed instead, in Settings).</p>
    <p>No mining, no ads, no hidden work. The <a href="https://github.com/roodolpha/MTGASIM" rel="noopener">source code</a> is public, so you can check.</p></div></section>
  <section class="block"><div class="actions" style="display:flex;gap:12px;flex-wrap:wrap">${downloadButtons()}<a class="btn" href="${DISCORD}" rel="noopener">Ask in the Discord</a></div></section>`;
  bindDownload();
}

async function privacyPage() {
  title("Privacy");
  const r = await fetch("/privacy.md").catch(() => null);
  const md = r && r.ok ? await r.text() : "See docs/PRIVACY.md in the source code.";
  const inline = (s) => s.replace(/\[(.+?)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>')
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/`(.+?)`/g, "<code>$1</code>");
  const html = esc(md).split(/\n\n+/).map((b) => b.startsWith("# ") ? `<h1>${inline(b.slice(2))}</h1>`
    : b.startsWith("## ") ? `<h2>${inline(b.slice(3))}</h2>`
    : /^- /.test(b) ? `<ul>${b.split(/\n(?=- )/).map((li) => `<li>${inline(li.slice(2))}</li>`).join("")}</ul>` : `<p>${inline(b)}</p>`).join("");
  $("#app").innerHTML = `<div class="prose">${html}</div>`;
}

function apiPage() {
  title("API");
  const ex = [["Meta for a format", "/v1/meta?format=standard"], ["Players", "/v1/leaderboard?format=brawl&days=30&min=50"],
    ["Matchups", "/v1/matchups?format=historic&top=8"], ["One public player", "/v1/players/NAME"]];
  $("#app").innerHTML = `<div class="pagehead"><h1>API</h1><p>Everything on this site comes from a free JSON API. No key needed. Responses are good for 5 minutes, so please cache them.</p></div>
  <div class="tablewrap" tabindex="0" role="region" aria-label="Table, scrolls sideways on small screens"><table><tbody>${ex.map(([t, e]) => `<tr><td style="width:180px">${t}</td><td><code>GET ${esc(API + e)}</code></td></tr>`).join("")}</tbody></table></div>
  <p class="note"><a href="https://github.com/roodolpha/MTGASIM/blob/main/docs/API.md">Full documentation</a></p>`;
}

function notFound() {
  title("Page not found");
  $("#app").innerHTML = `<div class="pagehead"><h1>There's no page here</h1><p>Try <a href="/meta">commanders and decks</a>, <a href="/players">players</a> or the <a href="/">home page</a>.</p></div>`;
}

const routes = [[/^\/$/, home], [/^\/home(?:\/(\w+))?\/?$/, (m) => { if (m[1]) setFmt(m[1]); return home(); }],
  [/^\/meta(?:\/(\w+))?\/?$/, metaPage], [/^\/(?:players|leaderboard)(?:\/(\w+))?\/?$/, players],
  [/^\/player\/(.+)$/, playerPage], [/^\/how\/?$/, howPage], [/^\/api\/?$/, apiPage], [/^\/privacy\/?$/, privacyPage]];
// real addresses (/meta/brawl), so search engines and link previews see each page; old #/ links still work
function go(path) { if (path !== location.pathname) history.pushState(null, "", path); route(); }
async function route() {
  if (location.hash.startsWith("#/")) history.replaceState(null, "", location.hash.slice(1) || "/");
  const h = location.pathname || "/";
  const nav = { meta: "/meta", player: "/players", players: "/players", leaderboard: "/players", how: "/how" }[(h.split("/")[1] || "")];
  document.querySelectorAll("nav.main a").forEach((a) => (a.getAttribute("href") === nav ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  if (PREV) PREV.remove(), (PREV = null);
  const hit = routes.find(([re]) => re.test(h));
  if (!hit) { notFound(); return; }
  $("#app").innerHTML = '<p class="loading">Loading</p>';
  try { await hit[1](h.match(hit[0])); }
  catch (e) {
    title("Couldn't load");
    $("#app").innerHTML = `<div class="pagehead"><h1>Couldn't load the numbers</h1><p>The Brewbench server didn't answer. Check your connection and try again; if it keeps happening, say so in the <a href="${DISCORD}">Discord</a>.</p>
      <p style="margin-top:20px"><button class="btn" type="button" id="retry">Try again</button></p></div>`;
    $("#retry").onclick = route;
  }
  window.scrollTo(0, 0);
}
// links within the site change the page without a reload
document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest("a[href^='/']");
  if (!a || a.target || a.hasAttribute("download") || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
  const href = a.getAttribute("href");
  if (/^\/(download|fonts|img)\b|\.\w+$/.test(href)) return;
  e.preventDefault(); go(href);
});
document.documentElement.classList.add("os-" + (OS === "phone" ? "other" : OS));
document.querySelectorAll("[data-download]").forEach((a) => (a.href = OS === "mac" ? "/download/mac" : "/download/windows"));
window.addEventListener("popstate", route);
window.addEventListener("hashchange", () => { if (location.hash.startsWith("#/")) route(); });
route();
