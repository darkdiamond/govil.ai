// 01 · כל המידע במקום אחד (18s) — hook → dot-grid of every dataset → ministries → CTA
export const duration = 18;
export default function (E) {
  const { stats: S0, he } = E;
  // 0–3.4 hook
  let s = E.seg(0, 3.6, { bg: "blue" });
  let c = s.safe();
  let h = s.add("div", "h1", null, null, c);
  s.words(h, "כמה מידע *ממשלתי* יש בישראל?", { at: 0.2, gap: 0.14 });
  let p = s.add("div", "p", "ניחשתם? הנה התשובה בעשר שניות", null, c);
  s.in(p, 1.8, "rise");
  s.confetti(18, { at: 0.1, y: 700, seed: 3, spread: 700 });

  // 3.4–9 dot grid
  s = E.seg(3.4, 5.8, { bg: "ink" });
  c = s.safe({ gap: 36 });
  const n = s.add("div", "big hl", "0", null, c);
  s.in(n, 0, "pop", 0.5);
  s.count(n, 0, S0.datasets, 0.2, 2.6);
  const t = s.add("div", "h2", "מאגרי מידע פתוחים", null, c);
  s.in(t, 0.3, "rise");
  const g = s.dotGrid(c, 28, S0.datasets, {
    at: 0.5,
    dur: 2.6,
    size: 22,
    gap: 11,
    alt: "#ffc107",
    altEvery: 14,
  });
  const t2 = s.add(
    "div",
    "h3",
    "כל אחד הופך לעמוד *מוסבר*, עם גרפים וסיכום בעברית".replace(
      /\*(.*?)\*/,
      "<span class=hl>$1</span>"
    ),
    null,
    c
  );
  s.in(t2, 3.4, "rise");

  // 9.2–13.8 ministries
  s = E.seg(9.2, 4.8, { bg: "light" });
  c = s.safe({ gap: 30 });
  let k = s.add("div", "kicker", "ממקורות רשמיים", null, c);
  s.in(k, 0, "pop");
  const o = s.add("div", "big hl", "0", null, c);
  s.in(o, 0.1, "pop");
  s.count(o, 0, S0.organizations, 0.3, 1.4);
  const o2 = s.add("div", "h2", "משרדים, רשויות ועיריות", null, c);
  s.in(o2, 0.4, "rise");
  const wrap = s.add(
    "div",
    null,
    null,
    {
      display: "flex",
      flexWrap: "wrap",
      gap: "18px",
      justifyContent: "center",
      marginTop: "10px",
    },
    c
  );
  S0.top_orgs.slice(0, 7).forEach(([name, cnt], i) => {
    const x = s.add(
      "div",
      "pill",
      `${name} <b class=num>${cnt}</b>`,
      { fontSize: "36px" },
      wrap
    );
    s.in(x, 1.0 + i * 0.28, i % 2 ? "slideL" : "slideR", 0.55);
  });

  // 13.8–18 CTA
  s = E.seg(13.8, 4.2, { bg: "blue" });
  c = s.safe({ gap: 50 });
  s.pulse(540, 760, "rgba(255,255,255,.5)", 0.2, { size: 420 });
  h = s.add("div", "h1", null, null, c);
  s.words(h, "הנתונים כבר *שלכם*", { at: 0.2, gap: 0.16 });
  p = s.add("div", "p", "גלו, חפשו והבינו — בלי להיות אנליסטים", null, c);
  s.in(p, 1.1, "rise");
  const b = s.add("div", "btn ltr", "govil.ai", null, c);
  s.in(b, 1.6, "pop");
  s.confetti(30, { at: 1.6, y: 1000, seed: 11 });
}
