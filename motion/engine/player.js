import { createEngine } from "/engine/engine.js";
const q = new URLSearchParams(location.search);
const name = q.get("scene");
const stats = await (await fetch("/data/stats.json")).json();
const E = createEngine(document.getElementById("stage"), stats);
const mod = await import(`/scenes/${name}.js`);
await mod.default(E);
E.finish(mod.duration);
await Promise.all(
  ["300", "500", "600", "700", "800"].map((w) =>
    document.fonts.load(`${w} 48px Rubik`, "אבג abc 123")
  )
);
await document.fonts.ready;
window.__duration = mod.duration;
window.__events = E.events;
window.__seek = (t) => E.seek(t);
window.__ready = true;
E.seek(0);
