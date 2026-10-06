// 19 · מה השתנה עם הזמן (S, 18s)
import { cta } from "./_kit.js";
export const duration = 18;
export default function (E) {
  const { stats: S } = E;
  let s = E.seg(0, 3.4, { bg: "ink", acc: "#0dcaf0" });
  let c = s.safe({ gap: 40 });
  const h = s.add("div", "h1", null, null, c);
  s.words(h, "מה *השתנה* עם השנים?", { at: 0.2, gap: 0.17 });
  const ic = s.add("div", null, E.icon("trend", 200, "#0dcaf0", 1.8), null, c);
  s.in(ic, 1, "pop");

  s = E.seg(3.1, 8.4, { bg: "blue", acc: "#ffc107" });
  c = s.safe({ gap: 26 });
  const n = s.add("div", "big hl", "0", { fontSize: "210px" }, c);
  s.in(n, 0.1, "pop");
  s.count(n, 0, S.kinds.timeseries, 0.3, 1.5);
  const l = s.add("div", "h2", "סדרות זמן", null, c);
  s.in(l, 0.5, "rise");
  const card = s.add(
    "div",
    "card",
    null,
    { width: "100%", padding: "40px", background: "rgba(255,255,255,.96)" },
    c
  );
  s.in(card, 1.0, "rise");
  const lab = s.add(
    "div",
    null,
    "מפלסי קידוחים",
    { fontSize: "44px", marginBottom: "14px", color: "#0c3058" },
    card
  );
  const r = E.rng(21);
  const pts = Array.from({ length: 16 }, (_, i) => [
    i / 15,
    Math.max(
      0.08,
      Math.min(
        0.92,
        0.55 + 0.22 * Math.sin(i / 2.2) - i * 0.015 + (r() - 0.5) * 0.12
      )
    ),
  ]);
  s.line(card, pts, {
    w: 820,
    h: 360,
    color: "#0068f5",
    at: 1.6,
    dur: 3.4,
    sw: 10,
    dots: false,
  });
  const pill = s.add(
    "div",
    "pill",
    "איור להמחשה בלבד",
    { fontSize: "30px", marginTop: "16px" },
    card
  );
  s.in(pill, 1.8, "fade");
  const t = s.add("div", "h3", null, null, c);
  s.words(t, "שנים. עשורים. *בגרף אחד*.", { at: 5.4, gap: 0.2 });

  s = E.seg(11.2, 4.2, { bg: "light" });
  c = s.safe({ gap: 24 });
  [
    "מפלסי קידוחים",
    "ספיקה רגעית בתחנות",
    "תקציב עיריית באר שבע",
    "מעיינות — נפחים חודשיים",
  ].forEach((t, i) => {
    const p = s.add(
      "div",
      "pill",
      E.icon("trend", 44, "#0068f5", 2.4) + t,
      { fontSize: "44px" },
      c
    );
    s.in(p, 0.2 + i * 0.3, i % 2 ? "slideL" : "slideR", 0.45);
  });
  cta(E, 15.2, 2.8, "הזמן *מספר*", "אתם רק צריכים להסתכל");
}
