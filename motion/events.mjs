// node events.mjs all|<scene>  -> data/events/<scene>.json  (sound-cue timeline recorded by the engine; no frames rendered)
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
const root = path.dirname(fileURLToPath(import.meta.url));
const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".woff2": "font/woff2",
};
const srv = http
  .createServer((q, r) => {
    const f = path.join(root, decodeURIComponent(q.url.split("?")[0]));
    if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) {
      r.writeHead(404);
      return r.end();
    }
    r.writeHead(200, {
      "content-type": MIME[path.extname(f)] || "application/octet-stream",
    });
    fs.createReadStream(f).pipe(r);
  })
  .listen(0);
await new Promise((r) => srv.on("listening", r));
const port = srv.address().port;
const list =
  process.argv[2] === "all"
    ? fs
        .readdirSync(path.join(root, "scenes"))
        .filter((f) => /^\d/.test(f))
        .map((f) => f.slice(0, -3))
        .sort()
    : [process.argv[2]];
const b = await puppeteer.launch({
  executablePath: process.env.CHROME || "/usr/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox"],
});
fs.mkdirSync(path.join(root, "data/events"), { recursive: true });
for (const sc of list) {
  const p = await b.newPage();
  p.on("pageerror", (e) => console.error(sc, e.message));
  await p.goto(`http://localhost:${port}/engine/player.html?scene=${sc}`);
  await p.waitForFunction("window.__ready === true");
  const ev = await p.evaluate(
    "({duration: window.__duration, events: window.__events})"
  );
  fs.writeFileSync(
    path.join(root, `data/events/${sc}.json`),
    JSON.stringify(ev)
  );
  console.log(sc, ev.duration, ev.events.length);
  await p.close();
}
await b.close();
srv.close();
