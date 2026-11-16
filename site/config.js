// Where the API lives. To point the site at another API for testing, open site/index.html?api=<address>
window.Brewbench_API = new URLSearchParams(location.search).get("api") || "https://brewbench-server.roododger.workers.dev";
// The Windows installer: always the newest release on GitHub (works once the repo is public).
window.Brewbench_DOWNLOAD = "https://github.com/roodolpha/MTGASIM/releases/latest/download/brewbench-setup.exe";
