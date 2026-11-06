const http = require("http");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const PORT = process.env.PORT || 10000;
const USERNAME = process.env.DASHBOARD_USERNAME || "owner";
const PASSWORD = process.env.DASHBOARD_PASSWORD;

if (!PASSWORD) {
  console.error("Missing DASHBOARD_PASSWORD environment variable.");
  process.exit(1);
}

const indexPath = path.join(__dirname, "index.html");
const sharePath = path.join(__dirname, "share.html");

function safeEqual(a, b) {
  const aa = Buffer.from(a);
  const bb = Buffer.from(b);
  return aa.length === bb.length && crypto.timingSafeEqual(aa, bb);
}

function sendHtml(res, filePath, headOnly) {
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(500, { "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" });
      return res.end("Page unavailable.");
    }
    res.writeHead(200, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "strict-origin-when-cross-origin"
    });
    if (headOnly) return res.end();
    res.end(data);
  });
}

http.createServer((req, res) => {
  const pathname = new URL(req.url, "http://localhost").pathname;

  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { "Allow": "GET, HEAD", "Cache-Control": "no-store" });
    return res.end("Method not allowed.");
  }

  if (pathname === "/favicon.ico") {
    res.writeHead(204, { "Cache-Control": "no-store" });
    return res.end();
  }

  // Public share page only. The private dashboard remains behind Basic Auth.
  if (pathname === "/share" || pathname === "/share/") {
    return sendHtml(res, sharePath, req.method === "HEAD");
  }

  const header = req.headers.authorization || "";
  const match = header.match(/^Basic (.+)$/i);
  let valid = false;

  if (match) {
    try {
      const decoded = Buffer.from(match[1], "base64").toString("utf8");
      const split = decoded.indexOf(":");
      if (split >= 0) {
        const user = decoded.slice(0, split);
        const pass = decoded.slice(split + 1);
        valid = safeEqual(user, USERNAME) && safeEqual(pass, PASSWORD);
      }
    } catch (_) {}
  }

  if (!valid) {
    res.writeHead(401, {
      "WWW-Authenticate": 'Basic realm="Private SocialDesk Dashboard", charset="UTF-8"',
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8"
    });
    return res.end("Login required.");
  }

  if (pathname !== "/" && pathname !== "/index.html") {
    res.writeHead(404, { "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" });
    return res.end("Not found.");
  }

  return sendHtml(res, indexPath, req.method === "HEAD");
}).listen(PORT, "0.0.0.0", () => {
  console.log("Private SocialDesk dashboard listening on port " + PORT);
});