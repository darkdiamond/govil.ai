// 06 · חיפוש בשנייה (S, 18s) — two live searches, results are real dataset titles
import { cta } from "./_kit.js";
export const duration = 18;
export default function (E) {
  const { stats: S } = E;
  const res = {
    מים: S.sector_top["הרשות הממשלתית למים ולביוב"].top.slice(0, 3),
    אוטובוס: S.sector_top["משרד התחבורה והבטיחות בדרכים"].top
      .filter((d) => /אוטובוס/.test(d.title))
      .slice(0, 3),
  };
  let s = E.seg(0, 3, { bg: "blue" });
  let c = s.safe();
  const h = s.add("div", "h1", null, null, c);
  s.words(h, "מחפשים *משהו*?", { at: 0.2, gap: 0.2 });
  const ic = s.add("div", null, E.icon("search", 260, "#fff", 1.8), null, c);
  s.in(ic, 0.8, "pop");

  [
    ["מים", 2.7],
    ["אוטובוס", 9.4],
  ].forEach(([q, at], qi) => {
    s = E.seg(at, qi ? 5.8 : 7, {
      bg: qi ? "ink" : "light",
      acc: qi ? "#ffc107" : "#0068f5",
    });
    c = s.safe({ gap: 28, justifyContent: "flex-start", top: "300px" });
    const box = s.add(
      "div",
      "card",
      null,
      {
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: "24px",
        borderRadius: "60px",
        padding: "30px 44px",
        fontSize: "64px",
      },
      c
    );
    s.in(box, 0.1, "rise");
    s.add("span", null, E.icon("search", 64, "#0068f5", 2.4), null, box);
    const txt = s.add("span", null, "", { flex: 1 }, box);
    s.type(txt, q, 0.6, 6);
    const tm = s.add("div", "p", null, { fontSize: "36px" }, c);
    tm.innerHTML = "התוצאות מופיעות מיד";
    s.in(tm, 1.6, "fade");
    res[q].forEach((d, i) => {
      const r = s.add(
        "div",
        "card",
        null,
        { width: "100%", display: "flex", alignItems: "center", gap: "24px" },
        c
      );
      s.add("span", null, E.icon("db", 64, "#0068f5", 2), { flexShrink: 0 }, r);
      s.add("span", null, d.title, { fontSize: "46px" }, r);
      s.in(r, 1.9 + i * 0.45, "slideR", 0.5);
    });
  });
  cta(E, 15.0, 3, "חפשו. *מצאתם*.", "ב־govil.ai");
}
