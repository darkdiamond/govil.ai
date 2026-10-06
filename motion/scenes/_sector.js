// Sector video template. S ≈ 20s, L ≈ 50s. All numbers/titles come from data/stats.json.
import { cta, datasetCard, hl, motif, pickSector, KIND_HE } from "./_kit.js";

export const DURATION = { S: 20, L: 50 };

export function sector(E, key, cfg) {
  const x = pickSector(E, key);
  const { he, mil } = E;
  const L = cfg.len === "L";
  const picks = cfg.picks.map((i) => x.top[i]);
  const acc = x.acc;

  // ── hook
  let s = E.seg(0, L ? 4.5 : 3.6, { bg: x.bg, acc });
  let c = s.safe({ gap: 50 });
  const badge = s.add(
    "div",
    null,
    E.icon(x.icon, 170, "#0c3058", 2.2),
    {
      width: "300px",
      height: "300px",
      borderRadius: "50%",
      background: acc,
      display: "grid",
      placeItems: "center",
      boxShadow: `0 0 0 24px ${acc}33`,
    },
    c
  );
  s.in(badge, 0, "pop", 0.7);
  s.pulse(540, 640, acc, 0.3, { size: 340 });
  let h = s.add("div", "h1", null, { fontSize: "118px" }, c);
  s.words(h, cfg.hook, { at: 0.5, gap: 0.13 });
  if (cfg.hookSub) {
    const p = s.add("div", "p", hl(cfg.hookSub), null, c);
    s.in(p, 1.9, "rise");
  }

  // ── the numbers (light card)
  let t0 = s.start + s.dur;
  let d0 = L ? 6 : 5;
  s = E.seg(t0 - 0.3 > 0 ? t0 - 0.3 : t0, d0 + 0.3, {
    bg: "light",
    acc: "#0068f5",
  }); // slight overlap = cross-fade
  const base = s.start;
  c = s.safe({ gap: 30 });
  let k = s.add("div", "kicker", x.name, null, c);
  s.in(k, 0.5, "pop");
  const n = s.add("div", "big hl", "0", null, c);
  s.in(n, 0.6, "pop");
  s.count(n, 0, x.datasets, 0.8, 1.5);
  const t = s.add("div", "h2", "מאגרי מידע פתוחים", null, c);
  s.in(t, 0.9, "rise");
  s.dotGrid(c, 20, Math.min(x.datasets, 100), {
    at: 1.2,
    dur: 1.6,
    size: 26,
    gap: 14,
    color: "#0068f5",
    alt: acc === "#ffc107" ? "#f59f00" : acc,
    altEvery: 6,
    seed: 5,
  });
  const rec = s.add(
    "div",
    "h3",
    `ובסך הכול *${mil(x.records)}* שורות נתונים`.replace(
      /\*(.*?)\*/,
      "<span class=hl>$1</span>"
    ),
    null,
    c
  );
  s.in(rec, 3.0, "rise");

  // ── spotlight / cards
  let cursor = base + s.dur - 0.3;
  if (!L) {
    s = E.seg(cursor, 7.2, { bg: x.bg, acc });
    c = s.safe({ gap: 34 });
    const hd = s.add("div", "h2", hl("מה *מסתתר* שם?"), null, c);
    s.in(hd, 0.2, "pop");
    picks.forEach((d, i) => datasetCard(E, s, c, d, 0.9 + i * 2.1, acc));
    cursor += 7.2 - 0.3;
  } else {
    picks.forEach((d, i) => {
      s = E.seg(cursor, 7.3, { bg: i % 2 ? "blue" : "ink", acc });
      c = s.safe({ gap: 34 });
      const lab = s.add(
        "div",
        "kicker",
        `מאגר ${i + 1} מתוך ${picks.length}`,
        { fontSize: "36px" },
        c
      );
      s.in(lab, 0.2, "pop");
      datasetCard(E, s, c, d, 0.5, acc);
      const m = motif(s, c, d.kind, 1.4, acc, 5 + i * 3);
      s.in(m, 1.2, "fade");
      const tag = s.add(
        "div",
        "p",
        "איור להמחשה בלבד",
        { fontSize: "30px", opacity: 0.55 },
        c
      );
      s.in(tag, 1.4, "fade");
      cursor += 7.3 - 0.3;
    });
    // ── questions
    s = E.seg(cursor, 8.3, { bg: "light", acc: "#0068f5" });
    c = s.safe({ gap: 34 });
    const hd = s.add("div", "h2", hl("מה אפשר *לגלות*?"), null, c);
    s.in(hd, 0.2, "pop");
    cfg.questions.forEach((q, i) => {
      const card = s.add(
        "div",
        "card",
        q,
        {
          width: "100%",
          fontSize: "54px",
          borderInlineStart: "16px solid #0068f5",
        },
        c
      );
      s.in(card, 1.0 + i * 2.0, "slideR");
    });
    cursor += 8.3 - 0.3;
    // ── records punch
    s = E.seg(cursor, 4.8, { bg: x.bg, acc });
    c = s.safe({ gap: 40 });
    const nn = s.add("div", "big hl", "0", { fontSize: "150px" }, c);
    s.in(nn, 0.2, "pop");
    s.count(nn, 0, x.records, 0.3, 2.2);
    const l1 = s.add("div", "h2", "שורות נתונים", null, c);
    s.in(l1, 0.4, "rise");
    const l2 = s.add("div", "h3", "מחכות שמישהו יקרא אותן", null, c);
    s.in(l2, 1.8, "rise");
    s.confetti(16, { at: 2.3, y: 900, seed: 21, colors: [acc, "#fff"] });
    cursor += 4.8 - 0.3;
  }
  cta(
    E,
    cursor,
    DURATION[cfg.len] - cursor,
    cfg.cta || "הנתונים כבר שלכם",
    cfg.ctaSub || `כל מאגרי ה${x.name} — מוסברים בעברית`,
    { acc, bg: "blue" }
  );
}
