// Where the API lives. To point the site at another API for testing, open site/index.html?api=<address>
window.Brewbench_API = new URLSearchParams(location.search).get("api") || "https://api.brewbench.gg";
