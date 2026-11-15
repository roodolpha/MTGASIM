// Where the API lives. For local testing: npx wrangler dev in server/, then open site/index.html?api=http://localhost:8787
window.Brewbench_API = new URLSearchParams(location.search).get("api") || "https://api.brewbench.gg";
