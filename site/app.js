// Brewbench public site: plain JS, reads the public API, no build step.
const API = window.Brewbench_API;
const FORMATS = [["brawl", "Historic Brawl"], ["standard", "Standard"], ["historic", "Historic"], ["standardbrawl", "Standard Brawl"], ["timeless", "Timeless"], ["alchemy", "Alchemy"]];
const NAMES = { W: "Mono-White", U: "Mono-Blue", B: "Mono-Black", R: "Mono-Red", G: "Mono-Green", C: "Colourless",
  WU: "Azorius", UB: "Dimir", BR: "Rakdos", RG: "Gruul", WG: "Selesnya", GW: "Selesnya", WB: "Orzhov", UR: "Izzet", BG: "Golgari", WR: "Boros", RW: "Boros", UG: "Simic",
  WUB: "Esper", UBR: "Grixis", BRG: "Jund", WRG: "Naya", WUG: "Bant", WBG: "Abzan", URW: "Jeskai", WUR: "Jeskai", BGU: "Sultai", UBG: "Sultai", WBR: "Mardu", URG: "Temur",
  WUBRG: "Five-colour" };

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => (x == null ? "–" : (100 * x).toFixed(1) + "%");
const pct0 = (x) => (x == null ? "–" : Math.round(100 * x) + "%");
const num = (n) => Number(n || 0).toLocaleString();
const isBrawl = (f) => f.endsWith("brawl");
const art = (name) => "https://api.scryfall.com/cards/named?format=image&version=art_crop&exact=" + encodeURIComponent(name);
const label = (deck, f) => (isBrawl(f) ? deck : NAMES[deck] || deck);
const pips = (c) => `<span class="pips" aria-hidden="true">${String(c || "").split("").map((x) => `<span class="pip" style="background:var(--${esc(x)})"></span>`).join("")}</span>`;
const fmtName = (f) => (FORMATS.find((x) => x[0] === f) || [f, f])[1];

// a small art thumbnail for Brawl commanders, a colour swatch for constructed archetypes
const thumb = (deck, colours, f) => {
  if (isBrawl(f) && deck) return `<span class="thumb" style="background-image:url('${esc(art(deck))}')"></span>`;
  const cs = String(colours || deck || "C").replace(/[^WUBRGC]/g, "").split("");
  const bg = cs.length > 1 ? `linear-gradient(90deg,${cs.map((x, i) => `var(--${x}) ${Math.round((i / cs.length) * 100)}% ${Math.round(((i + 1) / cs.length) * 100)}%`).join(",")})` : `var(--${cs[0] || "C"})`;
  return `<span class="thumb" style="background:${bg};opacity:.8"></span>`;
};
// where the true win rate probably sits (95% range), with the point estimate and 50% marked
const ci = (r) => {
  if (!r || !r.ci95) return "";
  const lo = Math.max(0, r.ci95[0]), hi = Math.min(1, r.ci95[1]);
  return `<span class="ci" title="Probably between ${pct0(lo)} and ${pct0(hi)}"><i style="left:${lo * 100}%;width:${(hi - lo) * 100}%"></i><b style="left:calc(${r.win_rate * 100}% - 1px)"></b></span>`;
};

async function get(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  return r.json();
}

let FMT = "brawl";
try { FMT = localStorage.getItem("fmt") || "brawl"; } catch (e) {}
function tabs() {
  return `<div class="tabs" role="tablist" aria-label="Format">${FORMATS.map(([k, n]) =>
    `<button role="tab" type="button" data-f="${k}" aria-selected="${k === FMT}">${n}</button>`).join("")}</div>`;
}
function bindTabs(rerender) {
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    FMT = b.dataset.f;
    try { localStorage.setItem("fmt", FMT); } catch (e) {}
    rerender();
  }));
}
const head = (title, text) => `<div class="pagehead"><h1>${title}</h1>${text ? `<p>${text}</p>` : ""}</div>`;

function deckTable(decks, f, { limit = 30, ranks = true, compact = false } = {}) {
  if (!decks.length) return `<div class="empty">Not enough shared games in ${esc(fmtName(f))} yet.</div>`;
  return `<div class="scroll"><table><thead><tr>${ranks ? "<th></th>" : ""}<th>Deck</th><th class="n">Play rate</th><th class="n">Ladder win rate</th><th>Range</th><th class="n">Sim win rate</th><th class="n">Games</th></tr></thead><tbody>
  ${decks.slice(0, limit).map((d, i) => `<tr>${ranks ? `<td class="rank">${i + 1}</td>` : ""}
    <td><div class="deckcell">${thumb(d.deck, d.colours, f)}<div style="min-width:0"><div class="dname">${esc(label(d.deck, f))}</div>${isBrawl(f) ? "" : `<span class="sub">${pips(d.colours || d.deck)}</span>`}</div></div></td>
    <td class="n">${pct(d.share)}</td>
    <td class="n wr">${d.real ? pct(d.real.win_rate) : "–"}</td>
    <td>${ci(d.real)}</td>
    <td class="n sim">${d.sim ? pct(d.sim.win_rate) : "–"}</td>
    <td class="n dim">${num(d.real ? d.real.games : 0)}${d.sim && !compact ? `<span class="sub">${num(d.sim.games)} simmed</span>` : ""}</td></tr>`).join("")}
  </tbody></table></div>`;
}

function playerTable(rows, f, compact) {
  if (!rows.length) return '<div class="empty">Nobody public with enough games yet.</div>';
  return `<div class="scroll"><table><thead><tr><th></th><th>Player</th>${compact ? "" : "<th>Main deck</th>"}<th class="n">Win rate</th>${compact ? "" : "<th>Range</th>"}<th class="n">Games</th></tr></thead><tbody>${rows.map((r) => `<tr>
   <td class="rank">${r.pos}</td>
   <td><a href="#/player/${encodeURIComponent(r.name)}" style="font-weight:500;text-decoration:none">${esc(r.name)}</a>${compact ? `<span class="sub">${esc(label(r.main_deck, f) || "")}</span>` : ""}</td>
   ${compact ? "" : `<td><div class="deckcell">${thumb(r.main_deck, r.colours, f)}<span class="dname">${esc(label(r.main_deck, f) || "")}</span></div></td>`}
   <td class="n wr">${pct(r.win_rate)}</td>${compact ? "" : `<td>${ci(r)}</td>`}
   <td class="n dim">${num(r.games)}</td></tr>`).join("")}</tbody></table></div>`;
}

// ------------------------------------------------------------------ pages
async function home() {
  const [meta, lb] = await Promise.all([get(`/v1/meta?format=${FMT}`), get(`/v1/leaderboard?format=${FMT}&min=20`)]);
  const decks = meta.decks.filter((d) => d.real && d.real.games >= 20);
  const top = decks[0];
  const simGames = meta.decks.reduce((n, d) => n + (d.sim ? d.sim.games : 0), 0);
  $("#app").innerHTML = head("What's winning on MTG Arena",
      "Real ladder results from players who share their games, next to what thousands of simulated games say. Last 30 days.") + tabs() + `
  <div class="kpis"><div><b>${num(meta.real_games)}</b><span>ladder games</span></div><div><b>${num(simGames)}</b><span>simulated games</span></div>
    <div><b>${num(meta.decks.length)}</b><span>${isBrawl(FMT) ? "commanders" : "archetypes"} seen</span></div><div><b>${num(lb.players.length)}</b><span>ranked players</span></div></div>
  <div class="cols"><div class="stack">
    ${top ? `<section class="panel"><div class="feature">
      ${isBrawl(FMT) ? `<div class="art" style="background-image:url('${esc(art(top.deck))}')" role="img" aria-label="${esc(top.deck)}"></div>` : `<div class="art">${thumb(top.deck, top.colours, FMT).replace('class="thumb"', 'class="thumb" style="width:100%;height:100%;border:0"')}</div>`}
      <div><div class="k">Top deck in ${esc(fmtName(FMT))}</div><h3>${esc(label(top.deck, FMT))}</h3>
      <div class="nums"><div><b>${pct(top.real.win_rate)}</b><span>ladder win rate</span></div><div><b class="sim">${top.sim ? pct(top.sim.win_rate) : "–"}</b><span>sim win rate</span></div>
      <div><b>${pct(top.share)}</b><span>of games</span></div><div><b>${num(top.real.games)}</b><span>games</span></div></div>
      ${isBrawl(FMT) ? `<div class="credit">Art via Scryfall</div>` : ""}</div></div></section>` : ""}
    <section class="panel"><header><h2>Top decks</h2><a href="#/meta">Full meta and matchups</a></header>${deckTable(decks, FMT, { limit: 10, compact: true })}</section>
  </div><div class="stack">
    <section class="panel"><header><h2>Top players, 30 days</h2><a href="#/leaderboard">All</a></header>${playerTable(lb.players.slice(0, 8), FMT, true)}</section>
    <section class="panel get"><div class="pad"><h2>Test your deck before you craft</h2>
      <p>Brewbench plays your list against the decks you actually face, on your own PC, thousands of times. Then it tells you whether a change really helped or you just got lucky.</p>
      <a class="btn primary" href="${esc(window.Brewbench_DOWNLOAD)}">Download for Windows</a> <a class="btn" href="https://github.com/roodolpha/MTGASIM">Source</a>
      <small>Free and open source. Until the app is signed, Windows may warn about an unknown publisher: choose More info, then Run anyway.</small></div></section>
  </div></div>`;
  bindTabs(home);
}

async function leaderboard() {
  const lb = await get(`/v1/leaderboard?format=${FMT}`);
  $("#app").innerHTML = head("Leaderboards", `Players who opted in, ${esc(lb.min_rank || "Platinum")} and up, last 30 days, at least ${lb.min_games} games. Self-reported from each player's own Arena log. The range shows where their true win rate probably sits.`)
    + tabs() + `<section class="panel">${playerTable(lb.players, FMT)}</section>`;
  bindTabs(leaderboard);
}

async function metaPage() {
  const [meta, mx] = await Promise.all([get(`/v1/meta?format=${FMT}`), get(`/v1/matchups?format=${FMT}&top=8`)]);
  const shade = (v) => {
    if (v == null) return "background:var(--s2);color:var(--faint)";
    const d = Math.max(-1, Math.min(1, (v - 0.5) / 0.15)), a = (Math.abs(d) * 0.55 + 0.08).toFixed(2);
    return `background:${d >= 0 ? `rgba(108,182,255,${a})` : `rgba(240,96,90,${a})`};color:var(--text)`;
  };
  $("#app").innerHTML = head("Meta", "Real ladder games from people who share, next to what the sim says. Last 30 days.") + tabs() + `
  <section class="panel"><header><h2>Decks</h2><span>${num(meta.real_games)} ladder games</span></header>${deckTable(meta.decks, FMT)}</section>
  <section class="panel" style="margin-top:20px"><header><h2>Matchups</h2><span>Row deck's win rate against the column deck</span></header>
  ${mx.decks.length ? `<div class="scroll" style="padding:8px"><table class="mx"><thead><tr><th></th>${mx.decks.map((d) => `<th scope="col">${esc(label(d, FMT))}</th>`).join("")}</tr></thead><tbody>
  ${mx.decks.map((a, i) => `<tr><th scope="row" style="white-space:nowrap;text-align:right">${esc(label(a, FMT))}</th>${mx.grid[i].map((c, j) => {
    const v = c.sim ? c.sim.win_rate : c.real ? c.real.win_rate : null;
    const tip = `${label(a, FMT)} vs ${label(mx.decks[j], FMT)}: sim ${c.sim ? pct0(c.sim.win_rate) + " over " + c.sim.games : "none"}, ladder ${c.real ? pct0(c.real.win_rate) + " over " + c.real.games : "none"}`;
    return `<td tabindex="0" title="${esc(tip)}" aria-label="${esc(tip)}" style="${shade(i === j ? null : v)}">${i === j ? "–" : pct0(v)}</td>`;
  }).join("")}</tr>`).join("")}</tbody></table></div>
  <div class="legend">Row loses <i></i> Row wins<span style="margin-left:auto">Simulated games where there are enough, ladder games otherwise. Hover a cell for both.</span></div>`
  : '<div class="empty">Not enough games for matchups yet.</div>'}</section>`;
  bindTabs(metaPage);
}

async function playerPage(name) {
  let p;
  try { p = await get(`/v1/players/${encodeURIComponent(name)}`); } catch (e) {
    $("#app").innerHTML = head(`No public player called ${esc(name)}`, "They might share anonymously, or under a different name."); return;
  }
  const w = p.weeks || [], max = 0.75, min = 0.25, W = 640, H = 200, L = 40, R = 12, T = 12, B = 24;
  const x = (i) => L + (i * (W - L - R)) / Math.max(1, w.length - 1), y = (v) => T + ((max - Math.max(min, Math.min(max, v))) / (max - min)) * (H - T - B);
  const grid = [0.3, 0.4, 0.5, 0.6, 0.7].map((g) => `<line x1="${L}" x2="${W - R}" y1="${y(g)}" y2="${y(g)}" stroke="${g === 0.5 ? "#2C313A" : "#1B1E24"}"/><text x="${L - 8}" y="${y(g) + 4}" text-anchor="end" fill="#5C636D" font-size="11">${g * 100}%</text>`).join("");
  $("#app").innerHTML = head(esc(p.name), `${num(p.games)} games shared`) + `
  <div class="kpis" style="margin-top:20px"><div><b>${pct(p.win_rate)}</b><span>win rate</span></div><div><b>${num(p.games)}</b><span>games</span></div>
    <div><b>${num((p.decks || []).length)}</b><span>decks</span></div><div><b>${w.length}</b><span>weeks active</span></div></div>
  <div class="cols"><div class="stack">
    <section class="panel"><header><h2>Win rate by week</h2></header><div class="pad">
    ${w.length > 1 ? `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Win rate by week">${grid}
      <polyline fill="none" stroke="#FF6B3D" stroke-width="2" points="${w.map((v, i) => x(i) + "," + y(v.win_rate)).join(" ")}"/>
      ${w.map((v, i) => `<circle cx="${x(i)}" cy="${y(v.win_rate)}" r="3" fill="#FF6B3D"><title>${esc(v.week)}: ${pct0(v.win_rate)} over ${v.games} games</title></circle>`).join("")}</svg>` : '<div class="empty">Needs a couple of weeks of games.</div>'}</div></section>
    <section class="panel"><header><h2>Against</h2></header>${(p.opponents || []).length ? `<table><thead><tr><th>Opponent</th><th class="n">Games</th><th class="n">Win rate</th></tr></thead><tbody>${p.opponents.map((o) => `<tr><td>${esc(o.opponent)}</td><td class="n dim">${num(o.games)}</td><td class="n wr">${pct(o.win_rate)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Not enough games yet.</div>'}</section>
  </div><div class="stack">
    <section class="panel"><header><h2>Decks</h2></header><table><tbody>${(p.decks || []).map((d) => `<tr><td><div class="deckcell">${thumb(d.commander, d.colours, d.format)}<div style="min-width:0"><div class="dname">${esc(label(d.commander || d.colours, d.format))}</div><span class="sub">${esc(fmtName(d.format))} · ${esc(d.first)} to ${esc(d.last)}</span></div></div></td><td class="n"><span class="wr">${pct(d.win_rate)}</span><span class="sub">${num(d.games)} games</span></td></tr>`).join("")}</tbody></table></section>
  </div></div>`;
}

async function players() {
  $("#app").innerHTML = head("Players", "Look up anyone who chose to share publicly.") + `
  <section class="panel" style="margin-top:20px"><div class="pad"><form id="f" class="search"><label for="q" class="dim" style="flex-basis:100%">Display name</label>
  <input id="q" required autocomplete="off"><button class="btn primary" type="submit">Look up</button></form></div></section>`;
  $("#f").onsubmit = (e) => { e.preventDefault(); location.hash = "#/player/" + encodeURIComponent($("#q").value.trim()); };
}

async function privacyPage() {
  const r = await fetch("privacy.md").catch(() => null);
  const md = r && r.ok ? await r.text() : "See docs/PRIVACY.md in the repo.";
  const html = esc(md).split(/\n\n+/).map((b) => b.startsWith("# ") ? `<h1>${b.slice(2)}</h1>`
    : b.startsWith("## ") ? `<h2>${b.slice(3)}</h2>` : `<p>${b}</p>`).join("")
    .replace(/\[(.+?)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>')
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/`(.+?)`/g, "<code>$1</code>");
  $("#app").innerHTML = `<section class="panel" style="margin-top:28px"><div class="prose">${html}</div></section>`;
}

function apiPage() {
  const ex = [["Meta for a format", "/v1/meta?format=standard"], ["Leaderboard", "/v1/leaderboard?format=brawl&days=30&min=50"],
    ["Matchup grid", "/v1/matchups?format=historic&top=8"], ["A public player", "/v1/players/NAME"]];
  $("#app").innerHTML = head("API", "Everything on this site comes from a free, open JSON API. No key needed. Please cache: responses are good for 5 minutes.") + `
  <section class="panel" style="margin-top:20px"><table><tbody>${ex.map(([t, e]) => `<tr><td style="width:200px" class="dim">${t}</td><td><code>GET ${esc(API + e)}</code></td></tr>`).join("")}</tbody></table>
  <div class="pad" style="border-top:1px solid var(--line)"><a href="https://github.com/roodolpha/MTGASIM/blob/main/docs/API.md">Full documentation</a></div></section>`;
}

document.querySelectorAll("[data-download]").forEach((a) => (a.href = window.Brewbench_DOWNLOAD));
const routes = [[/^#\/?$/, home], [/^#\/meta$/, metaPage], [/^#\/leaderboard$/, leaderboard], [/^#\/players$/, players],
  [/^#\/player\/(.+)$/, (m) => playerPage(decodeURIComponent(m[1]))], [/^#\/api$/, apiPage], [/^#\/privacy$/, privacyPage]];
async function route() {
  const h = location.hash || "#/";
  document.querySelectorAll("nav.main a").forEach((a) => (h.startsWith(a.getAttribute("href")) ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  for (const [re, fn] of routes) {
    const m = h.match(re);
    if (m) {
      try { await fn(m); } catch (e) { $("#app").innerHTML = head("Couldn't reach the data", esc(e.message)); }
      window.scrollTo(0, 0);
      return;
    }
  }
  home();
}
window.addEventListener("hashchange", route);
route();
