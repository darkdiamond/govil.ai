// Usage:
//   node render.mjs <scene> [--fps 30] [--stills 1,5,9]   scene = file name in scenes/ without .js
//   node render.mjs all [--jobs 4]                        render every scene
// Output: out/<scene>.mp4  (1080x1920, H.264, silent)  |  out/stills/<scene>-<t>.png
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
const root = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const flag = (n, d) => {
  const i = args.indexOf("--" + n);
  return i < 0 ? d : args[i + 1];
};
const target = args[0];
const fps = +flag("fps", 30);
const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".woff2": "font/woff2",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};
function serve() {
  return new Promise((res) => {
    const s = http
      .createServer((q, r) => {
        const u = decodeURIComponent(q.url.split("?")[0]);
        const f = path.join(root, u === "/" ? "engine/player.html" : u);
        if (
          !f.startsWith(root) ||
          !fs.existsSync(f) ||
          fs.statSync(f).isDirectory()
        ) {
          r.writeHead(404);
          return r.end();
        }
        r.writeHead(200, {
          "content-type": MIME[path.extname(f)] || "application/octet-stream",
        });
        fs.createReadStream(f).pipe(r);
      })
      .listen(0, () => res(s));
  });
}
async function open(browser, port, scene) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => console.error("PAGE ERROR", scene, e.message));
  page.on("console", (m) => {
    if (m.type() === "error") console.error("CONSOLE", scene, m.text());
  });
  await page.goto(`http://localhost:${port}/engine/player.html?scene=${scene}`);
  await page.waitForFunction("window.__ready === true", { timeout: 60000 });
  return page;
}
async function one(scene) {
  const server = await serve();
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME || "/usr/bin/google-chrome",
    headless: "new",
    args: [
      "--no-sandbox",
      "--font-render-hinting=none",
      "--hide-scrollbars",
      "--force-color-profile=srgb",
    ],
  });
  const page = await open(browser, port, scene);
  const dur = await page.evaluate("window.__duration");
  const stills = flag("stills", null);
  if (stills) {
    fs.mkdirSync(path.join(root, "out/stills"), { recursive: true });
    for (const t of stills.split(",")) {
      await page.evaluate((t) => window.__seek(t), +t);
      await page.screenshot({
        path: path.join(root, `out/stills/${scene}-${t}.png`),
      });
    }
  } else {
    fs.mkdirSync(path.join(root, "out/silent"), { recursive: true });
    const out = path.join(root, `out/silent/${scene}.mp4`);
    const n = Math.round(dur * fps);
    const ff = spawn(
      "ffmpeg",
      [
        "-y",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-framerate",
        String(fps),
        "-c:v",
        "mjpeg",
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-r",
        String(fps),
        out,
      ],
      { stdio: ["pipe", "inherit", "inherit"] }
    );
    for (let i = 0; i < n; i++) {
      await page.evaluate((t) => window.__seek(t), i / fps);
      const buf = await page.screenshot({
        type: "jpeg",
        quality: 92,
        optimizeForSpeed: true,
      });
      if (!ff.stdin.write(buf))
        await new Promise((r) => ff.stdin.once("drain", r));
    }
    ff.stdin.end();
    await new Promise((r) => ff.on("close", r));
    console.log(`done ${scene} ${dur}s -> ${out}`);
  }
  await browser.close();
  server.close();
}
if (target === "all") {
  const jobs = +flag("jobs", 4);
  const list = fs
    .readdirSync(path.join(root, "scenes"))
    .filter((f) => f.endsWith(".js") && !f.startsWith("_"))
    .map((f) => f.slice(0, -3))
    .sort();
  const q = [...list];
  await Promise.all(
    Array.from({ length: jobs }, async () => {
      while (q.length) {
        const s = q.shift();
        await new Promise((r) =>
          spawn(
            "node",
            [fileURLToPath(import.meta.url), s, "--fps", String(fps)],
            { stdio: "inherit" }
          ).on("close", r)
        );
      }
    })
  );
} else await one(target);
