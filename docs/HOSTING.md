# Putting the site online

The site (`site/`) is static files on Cloudflare Pages. The API it talks to runs on a Cloudflare Worker with a
D1 database; its code is kept in a separate private repo so the anti-abuse rules aren't published. What the API
does and how to call it is all in [API.md](API.md).

Expected cost at launch: £0 on Cloudflare's free tier, plus a domain (about £10 a year).

## The site

1. Put the API address in `site/config.js`.
2. Cloudflare dashboard > Workers & Pages > Create > Pages > connect this GitHub repo,
   build command empty, output directory `site`.
3. Add your domain under Pages > Custom domains.
4. Change `DEFAULT_API` in `brewbench/share.py` to the API address and release a new version of the app.

## Trying the site locally

```
python -m http.server 8090 --directory site
# open http://localhost:8090/?api=https://<the API address>
```

## Running your own server

Brewbench is GPL-3.0, so you're free to build your own API that speaks the protocol in [API.md](API.md) and
point the app at it with `brewbench share --api <address>`.
