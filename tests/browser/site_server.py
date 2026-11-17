"""Serves site/ like the real Worker does for the browser tests: files as they are, and index.html for page
addresses (/meta/brawl, /player/x), so real-path routing can be tested without Cloudflare."""
import http.server, os, re, sys

PAGES = re.compile(r"^/(home|meta|players|leaderboard|player|how|api|privacy)(/.*)?$")


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if PAGES.match(path):
            self.path = "/index.html"
        elif path != "/" and "." not in path.rsplit("/", 1)[-1] and not os.path.exists(path.lstrip("/")):
            # like the Worker: an unknown page address gets the site's own "page not found", status 404
            body = open("index.html", "rb").read()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.chdir(sys.argv[2])
    http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
