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

function safeEqual(a, b) {
  const aa = Buffer.from(a);
  const bb = Buffer.from(b);
  return aa.length === bb.length && crypto.timingSafeEqual(aa, bb);
}

http.createServer((req, res) => {
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
      "WWW-Authenticate": 'Basic realm="Private SocialDesk Demo", charset="UTF-8"',
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8"
    });
    return res.end("Login required.");
  }

  if (req.url !== "/" && req.url !== "/index.html") {
    res.writeHead(404, { "Cache-Control": "no-store" });
    return res.end("Not found");
  }

  fs.readFile(indexPath, (err, data) => {
    if (err) {
      res.writeHead(500);
      return res.end("Dashboard file unavailable.");
    }
    res.writeHead(200, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Referrer-Policy": "no-referrer"
    });
    res.end(data);
  });
}).listen(PORT, "0.0.0.0", () => {
  console.log("Private dashboard server listening on port " + PORT);
});
