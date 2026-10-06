// 05 · נתונים שמסבירים את עצמם (S, 20s)
import { cta } from "./_kit.js";
export const duration = 20;
export default function (E) {
  const { stats: S } = E;
  const sm = S.summaries.find((x) => /RECALL/.test(x.title)) || S.summaries[0];
  let s = E.seg(0, 4.6, { bg: "ink" });
  const r = E.rng(8);
  const grid = s.add(
    "div",
    "abs",
    null,
    {
      left: "40px",
      right: "40px",
      top: "260px",
      display: "grid",
      gridTemplateColumns: "repeat(5,1fr)",
      gap: "10px",
      direction: "ltr",
      fontFamily: "Noto Sans Mono, monospace",
      fontSize: "34px",
      color: "#7fb0ff",
      opacity: 0.55,
    },
    s.el
  );
  for (let i = 0; i < 70; i++)
    s.add(
      "div",
      null,
      String(Math.floor(r() * 90000) + 1000),
      { padding: "10px 6px", borderBottom: "1px solid rgba(255,255,255,.12)" },
      grid
    );
  s.anim(
    grid,
    [{ translate: "0 0" }, { translate: "0 -380px" }],
    0,
    4.6,
    "lin"
  );
  const c = s.safe({ gap: 30, top: "700px" });
  const h = s.add(
    "div",
    "h1",
    null,
    { textShadow: "0 6px 40px #06182f, 0 0 20px #06182f" },
    c
  );
  s.words(h, "קובץ עם מיליון מספרים. *מה* עושים איתו?", { at: 0.3, gap: 0.13 });

  s = E.seg(4.3, 8.2, { bg: "light" });
  let c2 = s.safe({ gap: 30 });
  const t = s.add(
    "div",
    "h2",
    "הופכים אותו ל*סיפור*".replace(/\*(.*?)\*/, "<span class=hl>$1</span>"),
    null,
    c2
  );
  s.in(t, 0.2, "pop");
  const card = s.add(
    "div",
    "card",
    null,
    { width: "100%", padding: "44px" },
    c2
  );
  s.in(card, 0.8, "rise");
  s.add(
    "div",
    null,
    sm.title,
    { fontSize: "40px", color: "#6c757d", marginBottom: "14px" },
    card
  );
  const bw = s.add(
    "div",
    null,
    null,
    { height: "300px", display: "flex", alignItems: "flex-end" },
    card
  );
  s.bars(bw, [0.25, 0.35, 0.3, 0.5, 0.45, 0.7, 0.62, 0.9], {
    w: 860,
    h: 300,
    color: "#0068f5",
    at: 1.2,
    stagger: 0.13,
    dur: 0.6,
    radius: 10,
  });
  const sum = s.add(
    "div",
    null,
    sm.summary,
    {
      fontSize: "44px",
      lineHeight: 1.35,
      marginTop: "24px",
      paddingTop: "22px",
      borderTop: "2px solid #e3eaf7",
    },
    card
  );
  s.in(sum, 3.0, "rise");
  const lab = s.add(
    "div",
    "p",
    "סיכום בעברית, גרף, והסבר — אוטומטית",
    { fontSize: "40px" },
    c2
  );
  s.in(lab, 4.2, "fade");
  s = E.seg(12, 3.4, { bg: "blue" });
  const c3 = s.safe({ gap: 36 });
  const k = s.add("div", "kicker", "בלי תואר בסטטיסטיקה", null, c3);
  s.in(k, 0.2, "pop");
  const h3 = s.add("div", "h1", null, null, c3);
  s.words(h3, "פשוט *להבין*", { at: 0.5, gap: 0.2 });
  cta(E, 15.2, 4.8, "מידע ש*מדבר* עברית", "תראו בעצמכם");
}
