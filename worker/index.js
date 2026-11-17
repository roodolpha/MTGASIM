// Serves the public site:
//  - pages at real addresses (/meta/brawl, /player/NAME): the same index.html, with the title, description and
//    link preview filled in for that page, so search engines and Discord/Reddit previews see the right thing
//  - /sitemap.xml and /robots.txt, built from the public API
//  - /download/*: installers streamed from the latest GitHub release, so they come from this address
//  - everything else: the static files in site/, with a real 404 for addresses that don't exist
const REPO = "roodolpha/MTGASIM";
const API = "https://brewbench-server.roododger.workers.dev";
const FILES = {
  windows: { asset: "brewbench-setup.exe", type: "application/vnd.microsoft.portable-executable" },
  mac: { asset: "brewbench-mac.zip", type: "application/zip" },
};
const FORMATS = { brawl: "Historic Brawl", standardbrawl: "Standard Brawl", standard: "Standard", historic: "Historic", timeless: "Timeless", alchemy: "Alchemy" };
const DEFAULT = {
  title: "Brewbench: play your Arena deck before you craft",
  description: "Brewbench plays your MTG Arena deck thousands of times against the commanders and decks you actually meet on ladder, on your own PC. Free and open source.",
};

const art = (name) => `https://api.scryfall.com/cards/named?exact=${encodeURIComponent(name)}&format=image&version=art_crop`;
const pct = (x) => Math.round(100 * x) + "%";
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path) {
  const r = await fetch(API + path, { cf: { cacheEverything: true, cacheTtl: 300 } });
  if (!r.ok) { const e = new Error("api " + r.status); e.status = r.status; throw e; }
  return r.json();
}

// what a page is called, how it's described, and its preview image; null: no such page
async function pageInfo(path) {
  let m;
  if (path === "/" || /^\/home(\/\w+)?\/?$/.test(path)) return { canonical: "/" };
  if ((m = path.match(/^\/meta(?:\/(\w+))?\/?$/))) {
    const f = FORMATS[m[1]] ? m[1] : "brawl", brawl = f.endsWith("brawl");
    const info = { canonical: `/meta/${f}`, title: `${brawl ? "Commanders" : "Decks"} on the ladder, ${FORMATS[f]} | Brewbench`,
      description: `${FORMATS[f]} win rates from real ladder games players shared, next to simulation results.` };
    try {
      const meta = await api(`/v1/meta?format=${f}`);
      const top = (meta.decks || []).filter((d) => d.real && d.real.games >= 20).sort((a, b) => b.real.games - a.real.games).slice(0, 3);
      if (top.length) {
        info.description = `${FORMATS[f]} on MTG Arena, from ${meta.real_games} shared ladder games: ` +
          top.map((d) => `${d.deck} ${pct(d.real.win_rate)}`).join(", ") + ". Win rates, likely ranges and matchups.";
        if (brawl) info.image = art(top[0].deck);
      }
    } catch (e) { /* the generic description is fine */ }
    return info;
  }
  if ((m = path.match(/^\/(?:players|leaderboard)(?:\/(\w+))?\/?$/))) {
    const f = FORMATS[m[1]] ? m[1] : "brawl";
    return { canonical: `/players/${f}`, title: `Players, ${FORMATS[f]} | Brewbench`,
      description: `MTG Arena players who share their ${FORMATS[f]} results publicly, ranked by win rate over the last 30 days.` };
  }
  if ((m = path.match(/^\/player\/([^/]+)\/?$/))) {
    const name = decodeURIComponent(m[1]);
    try {
      const p = await api(`/v1/players/${encodeURIComponent(name)}`);
      const main = (p.decks || []).slice().sort((a, b) => b.games - a.games)[0];
      const deck = main && (main.commander || main.colours);
      return { canonical: `/player/${encodeURIComponent(p.name)}`, title: `${p.name} | Brewbench`,
        description: `${p.name} on MTG Arena: ${p.games} games shared, ${pct(p.win_rate)} won${deck ? `, mostly ${deck}` : ""}.`,
        image: main && main.commander ? art(main.commander) : null };
    } catch (e) {
      if (e.status === 404) return { status: 404, canonical: path, title: "No such player | Brewbench" };
      return { canonical: path, title: `${name} | Brewbench` };
    }
  }
  const fixed = {
    "/how": ["How it works", "How Brewbench simulates your MTG Arena deck: install, one Arena setting, Test a change, and what Forge's AI can't do."],
    "/privacy": ["Privacy", "What Brewbench reads, what it sends if you turn sharing on, and what this website loads."],
    "/api": ["API", "The free JSON API behind the Brewbench site: meta, players, matchups."],
  }[path.replace(/\/$/, "")];
  if (fixed) return { canonical: path.replace(/\/$/, ""), title: `${fixed[0]} | Brewbench`, description: fixed[1] };
  return null;
}

async function page(request, env, info, origin) {
  const index = await env.ASSETS.fetch(new Request(origin + "/", request));
  const t = info.title || DEFAULT.title, d = info.description || DEFAULT.description, url = origin + (info.canonical || "/");
  const set = (attr, v) => ({ element: (el) => el.setAttribute(attr, v) });
  let rw = new HTMLRewriter()
    .on("title", { element: (el) => el.setInnerContent(t) })
    .on('meta[name="description"]', set("content", d))
    .on('link[rel="canonical"]', set("href", url))
    .on('meta[property="og:url"]', set("content", url))
    .on('meta[property="og:title"]', set("content", t))
    .on('meta[property="og:description"]', set("content", d));
  if (info.image) {
    rw = rw.on('meta[property="og:image"]', set("content", info.image))
      .on('meta[property="og:image:width"]', { element: (el) => el.remove() })
      .on('meta[property="og:image:height"]', { element: (el) => el.remove() });
  }
  if (info.status === 404) rw = rw.on("head", { element: (el) => el.append('<meta name="robots" content="noindex">', { html: true }) });
  const headers = new Headers(index.headers);
  headers.set("Content-Type", "text/html; charset=utf-8");
  headers.set("Cache-Control", "public, max-age=300");
  return rw.transform(new Response(index.body, { status: info.status || 200, headers }));
}

async function sitemap(origin) {
  const urls = ["/", "/how", "/privacy", "/api"];
  for (const f of Object.keys(FORMATS)) {
    urls.push(`/meta/${f}`, `/players/${f}`);
    try {
      const lb = await api(`/v1/leaderboard?format=${f}`);
      for (const p of lb.players || []) urls.push(`/player/${encodeURIComponent(p.name)}`);
    } catch (e) { /* skip this format's players */ }
  }
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    [...new Set(urls)].map((u) => `  <url><loc>${esc(origin + u)}</loc></url>`).join("\n") + "\n</urlset>\n";
  return new Response(body, { headers: { "Content-Type": "application/xml; charset=utf-8", "Cache-Control": "public, max-age=3600" } });
}

async function download(request, which) {
  if (request.method !== "GET" && request.method !== "HEAD") return new Response("Method not allowed", { status: 405 });
  const f = FILES[which || "windows"] || Object.values(FILES).find((x) => x.asset === which);
  if (!f) return new Response("Not found", { status: 404 });
  const headers = { "User-Agent": "brewbench-site" };
  const range = request.headers.get("Range");
  if (range) headers.Range = range;
  const up = await fetch(`https://github.com/${REPO}/releases/latest/download/${f.asset}`, {
    headers, redirect: "follow", cf: { cacheEverything: true, cacheTtl: 600 },
  });
  if (!up.ok && up.status !== 206) return new Response("Download is unavailable right now. Try again in a minute.", { status: 502 });
  const out = new Headers();
  for (const h of ["Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"]) {
    const v = up.headers.get(h);
    if (v) out.set(h, v);
  }
  out.set("Content-Type", f.type);
  out.set("Content-Disposition", `attachment; filename="${f.asset}"`);
  out.set("Cache-Control", "public, max-age=300");
  return new Response(request.method === "HEAD" ? null : up.body, { status: up.status, headers: out });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url), path = url.pathname;
    const dl = path.match(/^\/download\/?([a-z.-]*)\/?$/);
    if (dl) return download(request, dl[1]);
    if (path === "/sitemap.xml") return sitemap(url.origin);
    if (path === "/robots.txt") {
      return new Response(`User-agent: *\nAllow: /\nDisallow: /admin.html\n\nSitemap: ${url.origin}/sitemap.xml\n`,
        { headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "public, max-age=86400" } });
    }
    if (path === "/favicon.ico") {
      const r = await env.ASSETS.fetch(new Request(url.origin + "/favicon.png", request));
      return new Response(r.body, { status: r.status, headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=86400" } });
    }
    if (request.method === "GET" || request.method === "HEAD") {
      const info = await pageInfo(path);
      if (info) return page(request, env, info, url.origin);
    }
    const res = await env.ASSETS.fetch(request);
    // an address that isn't a page or a file: the site's own "page not found", with a real 404 status
    if (res.status === 404 && (request.headers.get("Accept") || "").includes("text/html")) {
      return page(request, env, { status: 404, canonical: path, title: "Page not found | Brewbench" }, url.origin);
    }
    return res;
  },
};
