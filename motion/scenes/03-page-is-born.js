// 03 · איך נולד עמוד באתר (L, 50s) — the 5-step pipeline, each step with its own mini-visual
import { cta } from "./_kit.js";
export const duration = 50;
export default function (E) {
  let s = E.seg(0, 4.8, { bg: "blue" });
  let c = s.safe({ gap: 44 });
  let h = s.add("div", "h1", null, null, c);
  s.words(h, "איך נולד *עמוד* חדש באתר?", { at: 0.2, gap: 0.15 });
  const p = s.add("div", "p", "חמישה שלבים. אפס ידיים.", null, c);
  s.in(p, 1.8, "rise");
  s.confetti(14, { at: 0.1, y: 900, seed: 4 });

  const steps = [
    {
      n: 1,
      ic: "search",
      t: "סורקים",
      d: "כל לילה בודקים מה חדש בפורטל הנתונים הממשלתי",
      vis: "radar",
    },
    {
      n: 2,
      ic: "db",
      t: "מורידים",
      d: "מושכים את הנתונים עצמם — כל הקבצים, כל השורות",
      vis: "rows",
    },
    {
      n: 3,
      ic: "zap",
      t: "מנתחים",
      d: "סוכן בינה מלאכותית כותב קוד, בונה גרפים ומסכם בעברית",
      vis: "code",
    },
    {
      n: 4,
      ic: "check",
      t: "בודקים",
      d: "בדיקות אוטומטיות: מספרים נכונים? עברית תקינה? הכול נגיש?",
      vis: "checks",
    },
    {
      n: 5,
      ic: "globe",
      t: "מפרסמים",
      d: "עמוד חדש עולה לאוויר — מוכן לקריאה בטלפון",
      vis: "page",
    },
  ];
  let at = 4.5;
  steps.forEach((st, i) => {
    s = E.seg(at, 7.4, {
      bg: i % 2 ? "blue" : "ink",
      acc: i % 2 ? "#ffc107" : "#0dcaf0",
    });
    c = s.safe({ gap: 30 });
    const num = s.add(
      "div",
      null,
      `${st.n}`,
      {
        position: "absolute",
        right: "40px",
        top: "190px",
        fontSize: "560px",
        fontWeight: 800,
        lineHeight: 1,
        color: "rgba(255,255,255,.07)",
      },
      s.el
    );
    s.in(num, 0, "zoom", 0.9);
    const badge = s.add(
      "div",
      null,
      E.icon(st.ic, 120, "#0c3058", 2.2),
      {
        width: "230px",
        height: "230px",
        borderRadius: "50%",
        background: "var(--acc)",
        display: "grid",
        placeItems: "center",
      },
      c
    );
    s.in(badge, 0.1, "pop");
    const t = s.add("div", "h1", st.t, null, c);
    s.in(t, 0.35, "rise");
    const d = s.add("div", "p", st.d, { maxWidth: "900px" }, c);
    s.in(d, 0.7, "rise");
    const v = s.add(
      "div",
      null,
      null,
      { width: "880px", height: "380px", position: "relative" },
      c
    );
    visual(E, s, v, st.vis);
    at += 7.1;
  });

  // recap strip
  s = E.seg(at, 4.8, { bg: "light" });
  c = s.safe({ gap: 36 });
  const hd = s.add(
    "div",
    "h2",
    "וכל זה — *כל לילה*".replace(/\*(.*?)\*/, "<span class=hl>$1</span>"),
    null,
    c
  );
  s.in(hd, 0.2, "pop");
  const row = s.add(
    "div",
    null,
    null,
    { display: "flex", gap: "20px", alignItems: "center" },
    c
  );
  steps.forEach((st, i) => {
    const b = s.add(
      "div",
      null,
      E.icon(st.ic, 80, "#fff", 2.2),
      {
        width: "150px",
        height: "150px",
        borderRadius: "50%",
        background: "#0068f5",
        display: "grid",
        placeItems: "center",
      },
      row
    );
    s.in(b, 0.6 + i * 0.35, "pop");
  });
  const lbl = s.add(
    "div",
    "h3",
    "סורקים ← מורידים ← מנתחים ← בודקים ← מפרסמים",
    { fontSize: "44px" },
    c
  );
  s.in(lbl, 2.6, "rise");
  at += 4.5;
  cta(E, at, 50 - at, "עמוד חדש *כל בוקר*", "ואתם רק צריכים לקרוא");
}
function visual(E, s, v, kind) {
  if (kind === "radar") {
    s.pulse(440, 190, "var(--acc)", 0.9, { n: 4, size: 220, dur: 2, gap: 0.6 });
    const dot = s.add(
      "div",
      "abs",
      null,
      {
        left: 440 - 30 + "px",
        top: "160px",
        width: "60px",
        height: "60px",
        borderRadius: "50%",
        background: "#fff",
      },
      v
    );
    s.in(dot, 0.9, "pop");
    [
      [120, 80],
      [700, 100],
      [180, 300],
      [650, 290],
      [420, 20],
    ].forEach(([x, y], i) => {
      const p = s.add(
        "div",
        "abs",
        E.icon("file", 70, "var(--acc)"),
        { left: x + "px", top: y + "px" },
        v
      );
      s.in(p, 2 + i * 0.5, "pop");
    });
  } else if (kind === "rows") {
    const box = s.add(
      "div",
      "abs",
      E.icon("db", 200, "var(--acc)", 1.8),
      { left: "340px", top: "90px" },
      v
    );
    s.in(box, 0.9, "pop");
    for (let i = 0; i < 14; i++) {
      const r = s.add(
        "div",
        "abs",
        null,
        {
          left: i % 2 ? "60px" : "760px",
          top: 20 + ((i * 53) % 330) + "px",
          width: "110px",
          height: "22px",
          borderRadius: "8px",
          background: i % 4 ? "#fff" : "var(--acc)",
        },
        v
      );
      s.anim(
        r,
        [
          { translate: "0 0", opacity: 0 },
          { opacity: 1, offset: 0.2 },
          { translate: `${i % 2 ? 330 : -330}px 0`, opacity: 0 },
        ],
        1 + i * 0.3,
        1.2,
        "in"
      );
    }
  } else if (kind === "code") {
    const term = s.add(
      "div",
      "abs",
      null,
      {
        inset: "0",
        borderRadius: "28px",
        background: "#06182f",
        border: "2px solid rgba(255,255,255,.18)",
        padding: "34px",
        direction: "ltr",
        textAlign: "left",
        fontFamily: "Noto Sans Mono, monospace",
        fontSize: "34px",
        lineHeight: 1.5,
        color: "#9fe3ff",
        whiteSpace: "pre",
      },
      v
    );
    const code = [
      'df = pd.read_csv("data.csv")',
      'df.groupby("year").sum()',
      "chart = echarts.bar(df)",
      'summary_he = "..."',
    ];
    code.forEach((ln, i) => {
      const l = s.add("div", null, "", null, term);
      s.type(l, ln, 1 + i * 1.2, 22, false);
    });
    const ch = s.add(
      "div",
      "abs",
      null,
      { right: "40px", bottom: "34px", width: "220px", height: "110px" },
      term
    );
    s.bars(ch, [0.4, 0.7, 0.5, 0.95, 0.8], {
      w: 220,
      h: 110,
      color: "#ffc107",
      at: 5,
      stagger: 0.1,
      dur: 0.5,
      radius: 6,
    });
  } else if (kind === "checks") {
    [
      "סכמה תקינה",
      "אין קישורים שבורים",
      "עברית ו־RTL",
      "נתונים תואמים למקור",
    ].forEach((t, i) => {
      const r = s.add(
        "div",
        "card",
        null,
        {
          display: "flex",
          alignItems: "center",
          gap: "20px",
          padding: "14px 30px",
          fontSize: "40px",
          marginBottom: "12px",
          width: "800px",
          marginInline: "auto",
        },
        v
      );
      const ck = s.add(
        "span",
        null,
        E.icon("check", 54, "#198754", 2.4),
        null,
        r
      );
      s.add("span", null, t, null, r);
      s.in(r, 1 + i * 0.8, "slideR", 0.5);
      s.in(ck, 1.5 + i * 0.8, "pop", 0.4);
    });
  } else {
    const pg = s.add(
      "div",
      "abs",
      null,
      {
        left: "230px",
        top: "0",
        width: "420px",
        height: "380px",
        borderRadius: "24px",
        background: "#fff",
        padding: "26px",
        overflow: "hidden",
      },
      v
    );
    s.in(pg, 0.9, "rise");
    s.add(
      "div",
      null,
      null,
      {
        height: "34px",
        borderRadius: "8px",
        background: "#0068f5",
        width: "100%",
      },
      pg
    );
    const bw = s.add("div", null, null, { marginTop: "24px" }, pg);
    s.bars(bw, [0.4, 0.6, 0.45, 0.9, 0.7, 0.85], {
      w: 360,
      h: 120,
      color: "#0068f5",
      at: 1.6,
      stagger: 0.12,
      dur: 0.5,
      radius: 6,
    });
    [1, 0.8, 0.9, 0.6].forEach((w, i) => {
      const l = s.add(
        "div",
        null,
        null,
        {
          height: "16px",
          width: w * 100 + "%",
          borderRadius: "8px",
          background: "#c3cfe7",
          marginTop: "14px",
          transformOrigin: "right center",
        },
        pg
      );
      s.in(l, 2.4 + i * 0.2, "grow", 0.5);
    });
    s.confetti(24, { at: 3.4, y: 1180, seed: 17 });
  }
}
