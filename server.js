const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 10000);
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".pdf": "application/pdf",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon"
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  let pathname;
  try { pathname = decodeURIComponent(url.pathname); }
  catch { res.writeHead(400); return res.end("Bad request"); }

  if (pathname === "/healthz") {
    res.writeHead(200, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
    return res.end("ok");
  }

  if (pathname === "/") pathname = "/index.html";
  const filePath = path.resolve(ROOT, "." + pathname);
  if (filePath !== ROOT && !filePath.startsWith(ROOT + path.sep)) {
    res.writeHead(403); return res.end("Forbidden");
  }

  fs.stat(filePath, (err, stat) => {
    if (err || !stat.isFile()) {
      res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      return res.end("Not found");
    }
    const headers = {
      "content-type": TYPES[path.extname(filePath).toLowerCase()] || "application/octet-stream",
      "x-content-type-options": "nosniff",
      "referrer-policy": "strict-origin-when-cross-origin"
    };
    if (pathname.startsWith("/data/")) headers["cache-control"] = "no-store";
    else headers["cache-control"] = "public, max-age=60";
    res.writeHead(200, headers);
    fs.createReadStream(filePath).pipe(res);
  });
});

server.listen(PORT, "0.0.0.0", () => {
  console.log("GeM Tender Dashboard listening on port " + PORT);
});
