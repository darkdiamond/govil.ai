// 18 · מפות (S, 18s) — pins clustering into numbered bubbles
import { cta } from "./_kit.js";
export const duration = 18;
export default function (E) {
  const { stats: S } = E;
  let s = E.seg(0, 3.4, { bg: "blue" });
  let c = s.safe({ gap: 40 });
  const n = s.add("div", "big hl", "0", null, c);
  s.in(n, 0.1, "pop");
  s.count(n, 0, S.kinds.map, 0.3, 1.4);
  const h = s.add("div", "h1", null, null, c);
  s.words(h, "מאגרים *על המפה*", { at: 0.6, gap: 0.18 });

  s = E.seg(3.1, 8.4, { bg: "ink", acc: "#5ee08a" });
  const W = 940,
    H = 1060;
  const box = s.add(
    "div",
    "abs",
    null,
    {
      left: "70px",
      top: "320px",
      width: W + "px",
      height: H + "px",
      borderRadius: "40px",
      background: "#0a2a4f",
      overflow: "hidden",
      border: "3px solid rgba(255,255,255,.18)",
    },
    s.el
  );
  s.in(box, 0.1, "rise");
  for (let i = 1; i < 12; i++)
    s.add(
      "div",
      "abs",
      null,
      {
        left: 0,
        right: 0,
        top: i * 88 + "px",
        height: i % 4 ? "2px" : "6px",
        background: "rgba(255,255,255,.1)",
      },
      box
    );
  for (let i = 1; i < 11; i++)
    s.add(
      "div",
      "abs",
      null,
      {
        top: 0,
        bottom: 0,
        left: i * 85 + "px",
        width: i % 3 ? "2px" : "6px",
        background: "rgba(255,255,255,.1)",
      },
      box
    );
  const r = E.rng(77);
  const clusters = [
    [250, 300, 14],
    [650, 380, 22],
    [420, 800, 17],
  ];
  clusters.forEach(([cx, cy, k], ci) => {
    const pins = [];
    for (let i = 0; i < k; i++) {
      const p = s.add(
        "div",
        "abs",
        E.icon("pin", 56, "#5ee08a", 2.4),
        {
          left: cx + (r() - 0.5) * 220 - 28 + "px",
          top: cy + (r() - 0.5) * 200 - 56 + "px",
        },
        box
      );
      s.in(p, 1 + ci * 0.5 + i * 0.06, "drop", 0.45, "back");
      s.out(p, 5.2 + ci * 0.25, "pop", 0.4);
      pins.push(p);
    }
    const b = s.add(
      "div",
      "abs",
      String(k),
      {
        left: cx - 70 + "px",
        top: cy - 70 + "px",
        width: "140px",
        height: "140px",
        borderRadius: "50%",
        background: "#5ee08a",
        color: "#0c3058",
        fontSize: "64px",
        fontWeight: 800,
        display: "grid",
        placeItems: "center",
        boxShadow: "0 0 0 18px rgba(94,224,138,.3)",
      },
      box
    );
    s.in(b, 5.4 + ci * 0.25, "pop", 0.5);
  });
  const cap = s.add(
    "div",
    "p",
    "איור להמחשה — כך נראים מאות אלפי נקודות כשמקבצים אותן",
    {
      position: "absolute",
      left: "70px",
      right: "70px",
      top: "1420px",
      fontSize: "34px",
      opacity: 0.6,
    },
    s.el
  );
  s.in(cap, 1.5, "fade");

  s = E.seg(11.2, 4.2, { bg: "light" });
  c = s.safe({ gap: 24 });
  const k = s.add("div", "h3", "אנטנות, עצים, תאורה, דפיברילטורים...", null, c);
  s.in(k, 0.1, "rise");
  ["אנטנות סלולריות", "עצים ברחובות", "עמודי תאורה", "דפיברילטורים"].forEach(
    (t, i) => {
      const p = s.add(
        "div",
        "pill",
        E.icon("pin", 44, "#0068f5", 2.4) + t,
        { fontSize: "44px" },
        c
      );
      s.in(p, 0.3 + i * 0.3, i % 2 ? "slideL" : "slideR", 0.45);
    }
  );
  cta(E, 15.2, 2.8, "כל נקודה — *סיפור*", "בעמוד אחד");
}
