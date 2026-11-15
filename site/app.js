// mtgasim public site: plain JS, reads the public API, no build step.
const API = window.MTGASIM_API;
const FORMATS = [["brawl", "Brawl"], ["standard", "Standard"], ["historic", "Historic"], ["standardbrawl", "Standard Brawl"], ["timeless", "Timeless"], ["alchemy", "Alchemy"]];
const NAMES = { W: "Mono-White", U: "Mono-Blue", B: "Mono-Black", R: "Mono-Red", G: "Mono-Green", C: "Colourless",
  WU: "Azorius", UB: "Dimir", BR: "Rakdos", RG: "Gruul", WG: "Selesnya", GW: "Selesnya", WB: "Orzhov", UR: "Izzet", BG: "Golgari", WR: "Boros", RW: "Boros", UG: "Simic",
  WUB: "Esper", UBR: "Grixis", BRG: "Jund", WRG: "Naya", WUG: "Bant", WBG: "Abzan", URW: "Jeskai", WUR: "Jeskai", BGU: "Sultai", UBG: "Sultai", WBR: "Mardu", URG: "Temur",
  WUBRG: "Five-colour" };

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => (x == null ? "–" : Math.round(100 * x) + "%");
const isBrawl = (f) => f.endsWith("brawl");
const art = (name) => "https://api.scryfall.com/cards/named?format=image&version=art_crop&exact=" + encodeURIComponent(name);
const label = (deck, f) => (isBrawl(f) ? deck : NAMES[deck] || deck);
const pips = (c) => `<span class="pips" aria-hidden="true">${String(c || "").split("").map((x) => `<span class="pip" style="background:var(--${esc(x)})"></span>`).join("")}</span>`;
const band = (c) => {
  const cs = String(c || "C").split("");
  return `<div style="height:100%;opacity:.85;background:linear-gradient(90deg,${cs.map((x, i) => `var(--${x}) ${Math.round((i / cs.length) * 100)}% ${Math.round(((i + 1) / cs.length) * 100)}%`).join(",")})"></div>`;
};
const pic = (deck, colours, f) => (isBrawl(f) && deck ? `<img src="${esc(art(deck))}" alt="" loading="lazy">` : band(colours || deck));

async function get(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  return r.json();
}

let FMT = localStorage.getItem("fmt") || "brawl";
function tabs(onPick) {
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
const fmtName = (f) => (FORMATS.find((x) => x[0] === f) || [f, f])[1];

// ------------------------------------------------------------------ pages
async function home() {
  const [meta, lb] = await Promise.all([get(`/v1/meta?format=${FMT}`), get(`/v1/leaderboard?format=${FMT}&min=20`)]);
  const decks = meta.decks.filter((d) => d.real && d.real.games >= 20).slice(0, 5);
  const top = decks[0];
  $("#app").innerHTML = `
  <div class="hero">${top && isBrawl(FMT) ? `<img src="${esc(art(top.deck))}" alt="">` : ""}
   <div class="in">${tabs()}
    ${top ? `<div class="kicker">#1 in ${esc(fmtName(FMT))} right now</div>
    <h1>${esc(label(top.deck, FMT))}</h1>
    <div style="display:flex;flex-wrap:wrap;gap:12px 36px;align-items:baseline">
     <div><span class="big">${pct(top.real.win_rate)}</span> <span class="dim">on ladder</span></div>
     <div><span class="big sim">${top.sim ? pct(top.sim.win_rate) : "–"}</span> <span class="dim">when the bots play it</span></div>
     <div class="dim">${pct(top.share)} of games</div></div>`
    : `<h1>${esc(fmtName(FMT))}</h1><p>Not enough games shared yet. Run the sim and share yours to get it going.</p>`}
   </div></div>
  <section><div class="sectionhead"><h2>What's winning</h2><a href="#/meta">Full meta + matchups →</a></div>
   <div class="grid">${decks.map((d, i) => `<a class="deck" href="#/meta"><div class="pic">${pic(d.deck, d.colours, FMT)}<span class="rank">#${i + 1}</span></div>
    <div class="body"><div style="font-weight:700">${pips(d.colours)}${esc(label(d.deck, FMT))}</div>
    <div style="display:flex;gap:18px"><div class="stat"><div class="l">Ladder</div><div class="v">${pct(d.real.win_rate)}</div></div>
    <div class="stat"><div class="l">Sim</div><div class="v sim">${d.sim ? pct(d.sim.win_rate) : "–"}</div></div></div>
    <div class="dim" style="font-size:13px">${d.real.games.toLocaleString()} games${d.sim ? " · " + d.sim.games.toLocaleString() + " simmed" : ""}</div></div></a>`).join("") || '<div class="empty">Nothing here yet.</div>'}</div></section>
  <section class="two"><div class="panel"><div class="sectionhead"><h2 style="font-size:26px">Top players this month</h2><a href="#/leaderboard">See all →</a></div>
   ${playerTable(lb.players.slice(0, 6))}</div>
   <div class="cta"><div style="display:flex;flex-direction:column;gap:10px"><h2>Play your deck 1,000 times before you craft that mythic.</h2>
   <p style="margin:0;font-size:17px">The sim runs your list against the decks you actually face, on your own PC, overnight. Then it tells you if that swap actually helped or if you just got lucky.</p></div>
   <div><a class="pill" href="https://github.com/roodolpha/MTGASIM">Download it, it's free</a></div></div></section>`;
  bindTabs(home);
}

function playerTable(rows) {
  if (!rows.length) return '<p class="dim">Nobody public with enough games yet.</p>';
  return `<div class="scroll"><table><tbody>${rows.map((r) => `<tr>
   <td style="width:40px"><span class="badge ${r.pos === 1 ? "gold" : r.pos <= 3 ? "top" : ""}">${r.pos}</span></td>
   <td><a href="#/player/${encodeURIComponent(r.name)}" style="color:var(--text);text-decoration:none;font-weight:700">${esc(r.name)}</a>
   <div class="dim" style="font-size:13px">${pips(r.colours)}${esc(label(r.main_deck, FMT) || "")}</div></td>
   <td class="n num" style="font-weight:800;font-size:20px">${pct(r.win_rate)}</td>
   <td class="n dim" style="font-size:14px">${pct(r.ci95[0])}–${pct(r.ci95[1])}</td>
   <td class="n dim" style="font-size:14px">${r.games} games</td></tr>`).join("")}</tbody></table></div>`;
}

async function leaderboard() {
  const lb = await get(`/v1/leaderboard?format=${FMT}`);
  $("#app").innerHTML = `<h1 style="font-size:48px;font-weight:800;margin:12px 0 6px">Leaderboards</h1>
  <p class="dim" style="margin:0 0 16px">Opted-in players at ${esc(lb.min_rank || "Platinum")} and up, last 30 days, at least ${lb.min_games} games. Results are self-reported from players' own logs. The range is where their real win rate probably sits.</p>
  ${tabs()}<div class="panel" style="margin-top:16px">${playerTable(lb.players)}</div>`;
  bindTabs(leaderboard);
}

async function metaPage() {
  const [meta, mx] = await Promise.all([get(`/v1/meta?format=${FMT}`), get(`/v1/matchups?format=${FMT}&top=8`)]);
  const shade = (v) => {
    if (v == null) return "background:var(--panel);color:var(--dim)";
    const d = Math.max(-1, Math.min(1, (v - 0.5) / 0.15));
    const a = Math.abs(d) * 0.75 + 0.1;
    return `background:${d >= 0 ? `rgba(124,196,255,${a})` : `rgba(255,107,61,${a})`};color:var(--text)`;
  };
  $("#app").innerHTML = `<h1 style="font-size:48px;font-weight:800;margin:12px 0 6px">The meta</h1>
  <p class="dim" style="margin:0 0 16px">Real ladder games from people who share, next to what the sim says. Last 30 days.</p>${tabs()}
  <section class="panel"><div class="scroll"><table><thead><tr><th>Deck</th><th class="n">Play rate</th><th class="n">Ladder</th><th class="n">Range</th><th class="n">Sim</th><th class="n">Games</th></tr></thead><tbody>
  ${meta.decks.slice(0, 30).map((d) => `<tr><td style="font-weight:700">${pips(d.colours || d.deck)}${esc(label(d.deck, FMT))}</td>
   <td class="n">${pct(d.share)}</td><td class="n num" style="font-weight:800">${d.real ? pct(d.real.win_rate) : "–"}</td>
   <td class="n dim">${d.real ? pct(d.real.ci95[0]) + "–" + pct(d.real.ci95[1]) : ""}</td>
   <td class="n sim" style="font-weight:700">${d.sim ? pct(d.sim.win_rate) : "–"}</td><td class="n dim">${d.real ? d.real.games : 0}${d.sim ? " + " + d.sim.games + " sim" : ""}</td></tr>`).join("")}
  </tbody></table></div></section>
  <section><div class="sectionhead"><h2>Who beats who</h2></div>
  <p class="dim" style="margin:-6px 0 12px">Row deck vs column deck, simulated games (ladder figure on hover). Blue: row wins more. Orange: row loses more.</p>
  <div class="panel scroll"><table class="mx"><thead><tr><th></th>${mx.decks.map((d) => `<th scope="col" style="text-align:center">${esc(label(d, FMT))}</th>`).join("")}</tr></thead><tbody>
  ${mx.decks.map((a, i) => `<tr><th scope="row" style="white-space:nowrap">${esc(label(a, FMT))}</th>${mx.grid[i].map((c, j) => {
    const v = c.sim ? c.sim.win_rate : c.real ? c.real.win_rate : null;
    const tip = `${label(a, FMT)} vs ${label(mx.decks[j], FMT)}: sim ${c.sim ? pct(c.sim.win_rate) + " (" + c.sim.games + ")" : "none"}, ladder ${c.real ? pct(c.real.win_rate) + " (" + c.real.games + ")" : "none"}`;
    return `<td tabindex="0" title="${esc(tip)}" aria-label="${esc(tip)}" style="${shade(i === j ? null : v)}">${i === j ? "mirror" : pct(v)}</td>`;
  }).join("")}</tr>`).join("")}</tbody></table></div></section>`;
  bindTabs(metaPage);
}

async function playerPage(name) {
  let p;
  try { p = await get(`/v1/players/${encodeURIComponent(name)}`); } catch (e) {
    $("#app").innerHTML = `<div class="empty"><h2>No public player called ${esc(name)}</h2><p>They might share anonymously.</p></div>`; return;
  }
  const w = p.weeks, max = 0.7, min = 0.3, W = 520, H = 180;
  const x = (i) => 30 + (i * (W - 50)) / Math.max(1, w.length - 1), y = (v) => 10 + ((max - Math.max(min, Math.min(max, v))) / (max - min)) * (H - 30);
  $("#app").innerHTML = `<div style="margin:16px 0 24px"><div class="kicker">Player</div><h1 style="font-size:64px;font-weight:800;line-height:1">${esc(p.name)}</h1>
  <p class="dim" style="margin:6px 0 0">${p.games} games shared · <span class="num" style="color:var(--text);font-weight:800">${pct(p.win_rate)}</span> won</p></div>
  <div class="two"><div class="panel"><h2 style="font-size:24px;margin-bottom:8px">Week by week</h2>
  <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Win rate by week" style="width:100%;height:auto">
   <line x1="30" x2="${W - 20}" y1="${y(0.5)}" y2="${y(0.5)}" stroke="#3A3A40" stroke-dasharray="4 4"/>
   <text x="24" y="${y(0.5) + 4}" text-anchor="end" fill="#A7A29A" font-size="12">50%</text>
   <polyline fill="none" stroke="#FF6B3D" stroke-width="3" points="${w.map((v, i) => x(i) + "," + y(v.win_rate)).join(" ")}"/>
   ${w.map((v, i) => `<circle cx="${x(i)}" cy="${y(v.win_rate)}" r="4" fill="#FF6B3D"><title>${esc(v.week)}: ${pct(v.win_rate)} over ${v.games}</title></circle>`).join("")}</svg></div>
  <div class="panel"><h2 style="font-size:24px;margin-bottom:8px">Decks</h2><table><tbody>${p.decks.map((d) => `<tr><td>${pips(d.colours)}<b>${esc(label(d.commander || d.colours, d.format))}</b><div class="dim" style="font-size:13px">${esc(fmtName(d.format))} · ${esc(d.first)} to ${esc(d.last)}</div></td><td class="n">${d.games} games</td><td class="n num" style="font-weight:800">${pct(d.win_rate)}</td></tr>`).join("")}</tbody></table></div></div>
  <section class="panel"><h2 style="font-size:24px;margin-bottom:8px">Against</h2><table><tbody>${p.opponents.map((o) => `<tr><td>${esc(o.opponent)}</td><td class="n dim">${o.games}</td><td class="n num" style="font-weight:800">${pct(o.win_rate)}</td></tr>`).join("") || '<tr><td class="dim">Not enough games yet.</td></tr>'}</tbody></table></section>`;
}

async function players() {
  $("#app").innerHTML = `<h1 style="font-size:48px;font-weight:800;margin:12px 0 16px">Find a player</h1>
  <form id="f" class="panel" style="display:flex;gap:10px;flex-wrap:wrap"><label for="q" class="dim" style="flex-basis:100%">Display name (only people who chose to be public)</label>
  <input id="q" required style="flex:1;min-width:200px;min-height:48px;border-radius:10px;border:1px solid var(--line);background:#0B0B0C;color:var(--text);padding:0 14px;font-size:16px">
  <button class="pill" type="submit">Look up</button></form>`;
  $("#f").onsubmit = (e) => { e.preventDefault(); location.hash = "#/player/" + encodeURIComponent($("#q").value.trim()); };
}

async function privacyPage() {
  const r = await fetch("privacy.md").catch(() => null);
  const md = r && r.ok ? await r.text() : "See docs/PRIVACY.md in the repo.";
  // tiny markdown: headings, bold, italics, paragraphs, inline code
  const html = esc(md).split(/\n\n+/).map((b) => b.startsWith("# ") ? `<h1 style="font-size:40px;font-weight:800">${b.slice(2)}</h1>`
    : b.startsWith("## ") ? `<h2 style="font-size:24px;margin-top:20px">${b.slice(3)}</h2>` : `<p>${b}</p>`).join("")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/`(.+?)`/g, "<code>$1</code>");
  $("#app").innerHTML = `<div class="panel" style="max-width:820px">${html}</div>`;
}

function apiPage() {
  const ex = ["/v1/meta?format=standard", "/v1/leaderboard?format=brawl&days=30&min=50", "/v1/matchups?format=historic&top=8", "/v1/players/NAME"];
  $("#app").innerHTML = `<h1 style="font-size:48px;font-weight:800;margin:12px 0 6px">API</h1>
  <p>Everything on this site comes from a free, open JSON API. No key needed; please cache (responses are good for 5 minutes).</p>
  <div class="panel">${ex.map((e) => `<p><code>GET ${esc(API + e)}</code></p>`).join("")}
  <p class="dim">Full docs: <a href="https://github.com/roodolpha/MTGASIM/blob/main/docs/API.md">docs/API.md</a></p></div>`;
}

const routes = [[/^#\/?$/, home], [/^#\/meta$/, metaPage], [/^#\/leaderboard$/, leaderboard], [/^#\/players$/, players],
  [/^#\/player\/(.+)$/, (m) => playerPage(decodeURIComponent(m[1]))], [/^#\/api$/, apiPage], [/^#\/privacy$/, privacyPage]];
async function route() {
  const h = location.hash || "#/";
  document.querySelectorAll("nav.main a").forEach((a) => a.setAttribute("aria-current", h.startsWith(a.getAttribute("href")) ? "page" : "false"));
  for (const [re, fn] of routes) {
    const m = h.match(re);
    if (m) {
      try { await fn(m); } catch (e) { $("#app").innerHTML = `<div class="empty"><h2>Couldn't reach the data</h2><p class="dim">${esc(e.message)}</p></div>`; }
      window.scrollTo(0, 0);
      return;
    }
  }
  home();
}
window.addEventListener("hashchange", route);
route();
