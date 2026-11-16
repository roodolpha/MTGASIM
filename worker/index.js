// Serves the static site, plus /download/* so installers come from this address rather than GitHub's.
// The files themselves are the latest GitHub release assets, streamed through and cached at the edge.
const REPO = "roodolpha/MTGASIM";
const FILES = {
  windows: { asset: "brewbench-setup.exe", type: "application/vnd.microsoft.portable-executable" },
  mac: { asset: "brewbench-mac.zip", type: "application/zip" },
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const m = url.pathname.match(/^\/download\/?([a-z.-]*)\/?$/);
    if (!m) return env.ASSETS.fetch(request);
    if (request.method !== "GET" && request.method !== "HEAD") return new Response("Method not allowed", { status: 405 });
    const which = m[1] || "windows";
    const f = FILES[which] || Object.values(FILES).find((x) => x.asset === which);
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
  },
};
