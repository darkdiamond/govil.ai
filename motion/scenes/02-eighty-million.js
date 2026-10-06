// 02 · 80 מיליון שורות (18s)
import { cta, hl } from "./_kit.js";
export const duration = 18;
export default function (E) {
  const { stats: S, he } = E;
  const years = Math.round(S.records / 525600); // one row per minute
  let s = E.seg(0, 3.8, { bg: "blue" });
  let c = s.safe();
  let h = s.add("div", "h1", null, null, c);
  s.words(h, "כמה *שורות* נתונים יש באתר?", { at: 0.2, gap: 0.14 });
  const q = s.add(
    "div",
    null,
    "?",
    {
      fontSize: "420px",
      fontWeight: 800,
      color: "rgba(255,255,255,.18)",
      lineHeight: 1,
    },
    c
  );
  s.in(q, 1.2, "zoom", 0.8);

  s = E.seg(3.5, 6.2, { bg: "ink" });
  // falling streams of "rows"
  for (let i = 0; i < 14; i++) {
    const r = E.rng(30 + i);
    const col = s.add(
      "div",
      "abs",
      null,
      {
        left: 70 + i * 69 + "px",
        top: 0,
        width: "34px",
        height: "1920px",
        overflow: "hidden",
        opacity: 0.5,
      },
      s.el
    );
    const strip = s.add(
      "div",
      null,
      null,
      { display: "flex", flexDirection: "column", gap: "22px" },
      col
    );
    for (let k = 0; k < 40; k++)
      s.add(
        "div",
        null,
        null,
        {
          height: 14 + r() * 26 + "px",
          borderRadius: "8px",
          background: r() > 0.85 ? "#ffc107" : "#3d7bd4",
        },
        strip
      );
    s.anim(
      strip,
      [{ translate: "0 -1800px" }, { translate: "0 200px" }],
      0,
      6.2,
      "lin"
    );
  }
  c = s.safe({ gap: 30 });
  const n = s.add(
    "div",
    "big hl",
    "0",
    { fontSize: "170px", textShadow: "0 8px 40px rgba(8,31,59,.9)" },
    c
  );
  s.in(n, 0.3, "pop");
  s.count(n, 0, S.records, 0.5, 3.4);
  const l = s.add(
    "div",
    "h2",
    "שורות של נתונים ציבוריים",
    { textShadow: "0 4px 30px rgba(8,31,59,.9)" },
    c
  );
  s.in(l, 1, "rise");
  const l2 = s.add(
    "div",
    "h3",
    `ב־${he(S.datasets)} מאגרים`,
    { textShadow: "0 4px 30px rgba(8,31,59,.9)" },
    c
  );
  s.in(l2, 4.0, "rise");

  s = E.seg(9.4, 5.2, { bg: "light" });
  c = s.safe({ gap: 34 });
  const p1 = s.add(
    "div",
    "h3",
    "נניח שקוראים *שורה אחת* בדקה...".replace(
      /\*(.*?)\*/,
      "<span class=hl>$1</span>"
    ),
    null,
    c
  );
  s.in(p1, 0.2, "rise");
  const ic = s.add("div", null, E.icon("clock", 220, "#0068f5", 1.8), null, c);
  s.in(ic, 0.5, "pop");
  s.anim(
    ic.firstChild,
    [{ rotate: "0deg" }, { rotate: "1440deg" }],
    0.5,
    3.4,
    "inout"
  );
  const yy = s.add("div", "big hl", "0", { fontSize: "230px" }, c);
  s.in(yy, 1.2, "pop");
  s.count(yy, 0, years, 1.3, 1.8);
  const yl = s.add("div", "h2", "שנים. בלי לישון.", null, c);
  s.in(yl, 3.1, "rise");

  cta(E, 14.2, 3.8, "קראנו אותן *בשבילכם*", "ותרגמנו לגרפים ולעברית פשוטה");
}
