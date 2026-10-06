// 09 · משרדים ורשויות (L, 50s) — bar race of who publishes the most
import { cta } from "./_kit.js";
export const duration = 50;
export default function (E) {
  const { stats: S, he } = E;
  const top = S.top_orgs.slice(0, 8);
  const mx = top[0][1];
  const pct = Math.round((mx / S.datasets) * 100);
  let s = E.seg(0, 4.6, { bg: "blue" });
  let c = s.safe({ gap: 40 });
  let h = s.add("div", "h1", null, null, c);
  s.words(h, "מי מפרסם *הכי הרבה* נתונים?", { at: 0.2, gap: 0.14 });
  const q = s.add("div", "p", "נעשה סדר", null, c);
  s.in(q, 1.6, "rise");

  s = E.seg(4.3, 17, { bg: "ink" });
  c = s.safe({ gap: 22, justifyContent: "flex-start", top: "280px" });
  const ttl = s.add("div", "h2", "מספר המאגרים לפי גוף", null, c);
  s.in(ttl, 0.1, "rise");
  const rows = top.map(([name, n], i) => {
    const r = s.add("div", null, null, { width: "100%" }, c);
    const lab = s.add(
      "div",
      null,
      name,
      { fontSize: "40px", fontWeight: 600, marginBottom: "8px" },
      r
    );
    const track = s.add(
      "div",
      null,
      null,
      {
        height: "56px",
        borderRadius: "50rem",
        background: "rgba(255,255,255,.1)",
        position: "relative",
        overflow: "hidden",
      },
      r
    );
    const fill = s.add(
      "div",
      null,
      null,
      {
        height: "100%",
        width: Math.max(8, (n / mx) * 100) + "%",
        borderRadius: "50rem",
        background: i === 0 ? "#ffc107" : i % 2 ? "#0dcaf0" : "#3d8bff",
        transformOrigin: "right center",
      },
      track
    );
    const num = s.add(
      "b",
      "num",
      "0",
      {
        position: "absolute",
        left: "24px",
        top: "0",
        lineHeight: "56px",
        fontSize: "38px",
        color: i === 0 ? "#0c3058" : "#fff",
        mixBlendMode: "normal",
      },
      track
    );
    const t = 1.0 + (top.length - 1 - i) * 1.55;
    s.in(r, t - 0.3, "slideR", 0.5);
    s.in(fill, t, "grow", 1.0);
    s.count(num, 0, n, t, 1.0);
  });
  s = E.seg(21, 8.2, { bg: "light" });
  c = s.safe({ gap: 30 });
  const ic = s.add("div", null, E.icon("bus", 200, "#0068f5", 1.8), null, c);
  s.in(ic, 0.2, "pop");
  const n = s.add("div", "big hl", "0%", { fontSize: "250px" }, c);
  s.in(n, 0.3, "pop");
  s.count(n, 0, pct, 0.5, 1.6, { suf: "%" });
  const l = s.add("div", "h2", "מהמאגרים הם של משרד התחבורה", null, c);
  s.in(l, 1, "rise");
  const l2 = s.add("div", "h3", `${he(mx)} מאגרים — יותר מכל גוף אחר`, null, c);
  s.in(l2, 2.4, "rise");

  s = E.seg(28.9, 8.3, { bg: "blue" });
  c = s.safe({ gap: 30 });
  const ic2 = s.add("div", null, E.icon("building", 200, "#fff", 1.8), null, c);
  s.in(ic2, 0.2, "pop");
  const city = top.find(([nm]) => nm.includes("באר שבע")) || top[2];
  const t = s.add("div", "h1", null, null, c);
  s.words(t, "גם *עיריות* מפרסמות", { at: 0.4, gap: 0.2 });
  const nn = s.add("div", "big hl", "0", { fontSize: "220px" }, c);
  s.in(nn, 1.2, "pop");
  s.count(nn, 0, city[1], 1.4, 1.4);
  const l3 = s.add("div", "h3", `מאגרים מ${city[0]} לבדה`, null, c);
  s.in(l3, 2.4, "rise");

  s = E.seg(36.9, 7.3, { bg: "ink" });
  c = s.safe({ gap: 30 });
  const k = s.add("div", "kicker", "ובסך הכול", null, c);
  s.in(k, 0.2, "pop");
  const o = s.add("div", "big hl", "0", null, c);
  s.in(o, 0.3, "pop");
  s.count(o, 0, S.organizations, 0.5, 1.6);
  const o2 = s.add("div", "h2", "גופים ציבוריים. אתר אחד.", null, c);
  s.in(o2, 1, "rise");
  s.confetti(18, { at: 2.0, y: 900, seed: 5 });
  cta(E, 44, 6, "כולם *במקום אחד*", "ואתם בוחרים מה לקרוא");
}
