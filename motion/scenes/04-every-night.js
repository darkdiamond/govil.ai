// 04 · כל לילה (S, 18s) — time-lapse clock 23:00 → 02:00
import { cta } from "./_kit.js";
export const duration = 18;
export default function (E) {
  let s = E.seg(0, 4, { bg: "ink" });
  let c = s.safe({ gap: 40 });
  const stars = E.rng(2);
  for (let i = 0; i < 40; i++) {
    const st = s.add(
      "div",
      "abs",
      null,
      {
        left: stars() * 1080 + "px",
        top: stars() * 1500 + "px",
        width: 6 + stars() * 8 + "px",
        height: 6 + stars() * 8 + "px",
        borderRadius: "50%",
        background: "#fff",
      },
      s.el
    );
    s.anim(
      st,
      [{ opacity: 0.15 }, { opacity: 1 }, { opacity: 0.15 }],
      stars() * 1.5,
      1.2 + stars(),
      "inout"
    );
  }
  const moon = s.add("div", null, E.icon("moon", 260, "#ffc107", 1.8), null, c);
  s.in(moon, 0, "pop", 0.8);
  s.drift(moon.firstChild, [{ rotate: "-8deg" }, { rotate: "8deg" }]);
  const h = s.add("div", "h1", null, null, c);
  s.words(h, "בזמן שאתם *ישנים*...", { at: 0.6, gap: 0.2 });

  s = E.seg(3.7, 8.2, { bg: "blue" });
  c = s.safe({ gap: 36 });
  const clock = s.add(
    "div",
    null,
    null,
    {
      width: "560px",
      height: "560px",
      borderRadius: "50%",
      border: "14px solid #fff",
      position: "relative",
      background: "rgba(255,255,255,.08)",
    },
    c
  );
  s.in(clock, 0, "pop");
  for (let i = 0; i < 12; i++)
    s.add(
      "div",
      "abs",
      null,
      {
        left: "259px",
        top: "10px",
        width: "14px",
        height: i % 3 ? "26px" : "44px",
        borderRadius: "8px",
        background: "#fff",
        transformOrigin: "7px 260px",
        transform: `rotate(${i * 30}deg)`,
      },
      clock
    );
  const hand = s.add(
    "div",
    "abs",
    null,
    {
      left: "263px",
      top: "90px",
      width: "12px",
      height: "190px",
      borderRadius: "8px",
      background: "#ffc107",
      transformOrigin: "6px 190px",
    },
    clock
  );
  s.anim(hand, [{ rotate: "330deg" }, { rotate: "390deg" }], 0.5, 5.8, "inout");
  s.add(
    "div",
    "abs",
    null,
    {
      left: "254px",
      top: "254px",
      width: "32px",
      height: "32px",
      borderRadius: "50%",
      background: "#fff",
    },
    clock
  );
  const dig = s.add("div", "big num hl", "23:00", { fontSize: "170px" }, c);
  s.in(dig, 0.3, "rise");
  const base = s.start;
  E.tick((t) => {
    const k = Math.min(1, Math.max(0, (t - base - 0.5) / 5.8));
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    const m = Math.round(e * 120);
    const hh = (23 + Math.floor(m / 60)) % 24;
    dig.textContent = `${String(hh).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  });
  const l = s.add("div", "h3", "הבנייה היומית יוצאת לדרך", null, c);
  s.in(l, 1.2, "rise");

  s = E.seg(11.6, 3.4, { bg: "light" });
  c = s.safe({ gap: 36 });
  const sun = s.add("div", null, E.icon("sun", 240, "#f59f00", 1.8), null, c);
  s.in(sun, 0, "pop");
  s.anim(
    sun.firstChild,
    [{ rotate: "-90deg" }, { rotate: "0deg" }],
    0,
    1.4,
    "out"
  );
  const t = s.add("div", "h1", null, null, c);
  s.words(t, "ובבוקר — *עמודים חדשים*", { at: 0.4, gap: 0.18 });
  cta(E, 14.7, 3.3, "מאגר חדש? *עמוד חדש*", "בלי שתצטרכו לבקש");
}
