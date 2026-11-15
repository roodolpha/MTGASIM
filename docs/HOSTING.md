# Putting the site online

Everything runs on Cloudflare's free tier: the API is a Worker with a D1 (SQLite) database, the site is static
files on Pages. Expected cost at launch: £0 plus a domain (about £10 a year).

Free tier limits that matter (check Cloudflare's docs, they change): Workers 100,000 requests a day; D1 5 GB,
5 million rows read and 100,000 written a day; Pages unlimited static requests, 500 builds a month.
Workers Paid ($5 a month) lifts all of these a long way if the site takes off.

## One-off setup

```
cd server
npm install -g wrangler        # or: npx wrangler ...
wrangler login
wrangler d1 create brewbench     # copy the database_id it prints into wrangler.toml
wrangler d1 execute brewbench --remote --file schema.sql
wrangler deploy                # prints the API's address, e.g. https://brewbench-api.<you>.workers.dev
```

Then the site:

1. Put the API address in `site/config.js`.
2. Cloudflare dashboard > Workers & Pages > Create > Pages > connect the GitHub repo,
   build command empty, output directory `site`.
3. Add your domain to both (Pages: Custom domains; Worker: Settings > Triggers > Custom domain, e.g. `api.yourdomain`).
4. Set `ALLOWED_ORIGIN` in `wrangler.toml` to your site's address if you want to stop other sites calling the
   write endpoints from a browser (reads stay open either way).
5. Change `DEFAULT_API` in `brewbench/share.py` to the API address and release a new version of the simulator.

## Trying it locally

```
cd server
npx wrangler d1 execute brewbench --local --file schema.sql
npx wrangler dev --local --port 8787
# another terminal, from the repo root:
python -m http.server 8090 --directory site
# open http://localhost:8090/?api=http://localhost:8787
brewbench share --api http://localhost:8787 --preview
```

## Looking after it

* Backups: `wrangler d1 export brewbench --remote --output backup.sql` (D1 also keeps 30 days of point-in-time
  history on the free plan).
* Abuse: uploads are capped per request and validated; if someone floods it, add a Cloudflare rate-limiting
  rule on `/v1/upload` and `/v1/register` (free plan includes one rule).
* Privacy requests: `brewbench share --forget` handles deletion itself; for anything else,
  `DELETE FROM clients WHERE display_name = '...'` (matches and sims cascade).
