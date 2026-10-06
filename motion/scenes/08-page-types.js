// 08 · שלושה סוגי עמודים (L, 50s) — registry / time series / map + download formats
import { cta, motif } from "./_kit.js";
export const duration = 50;
export default function (E) {
  const { stats: S, he } = E;
  const K = S.kinds;
  let s = E.seg(0, 4.6, { bg: "blue" });
  let c = s.safe({ gap: 40 });
  let h = s.add("div", "h1", null, null, c);
  s.words(h, "לכל מאגר יש *אופי*", { at: 0.2, gap: 0.2 });
  const p = s.add("div", "p", "והעמוד מתאים את עצמו אליו", null, c);
  s.in(p, 1.4, "rise");
  const types = [
    {
      k: "registry",
      t: "מאגר רשומות",
      d: "טבלאות ענק שאפשר לסנן, לחפש ולהוריד",
      ic: "file",
      acc: "#ffc107",
      bg: "ink",
    },
    {
      k: "timeseries",
      t: "סדרות זמן",
      d: "איך משהו משתנה לאורך השנים — בגרף אחד",
      ic: "trend",
      acc: "#0dcaf0",
      bg: "blue",
    },
    {
      k: "map",
      t: "מפות",
      d: "כל נקודה על המפה היא שורה בנתונים",
      ic: "pin",
      acc: "#5ee08a",
      bg: "ink",
    },
  ];
  let at = 4.3;
  types.forEach((t, i) => {
    s = E.seg(at, 8.9, { bg: t.bg, acc: t.acc });
    c = s.safe({ gap: 28 });
    const b = s.add(
      "div",
      null,
      E.icon(t.ic, 120, "#0c3058", 2.2),
      {
        width: "210px",
        height: "210px",
        borderRadius: "50%",
        background: t.acc,
        display: "grid",
        placeItems: "center",
      },
      c
    );
    s.in(b, 0.1, "pop");
    const n = s.add("div", "big hl", "0", { fontSize: "230px" }, c);
    s.in(n, 0.3, "pop");
    s.count(n, 0, K[t.k], 0.5, 1.6);
    const l = s.add("div", "h1", t.t, { fontSize: "100px" }, c);
    s.in(l, 0.7, "rise");
    const d = s.add("div", "p", t.d, null, c);
    s.in(d, 1.2, "rise");
    const m = motif(s, c, t.k, 2.2, t.acc, 9 + i * 4);
    s.in(m, 2.0, "fade");
    const tag = s.add(
      "div",
      "p",
      "איור להמחשה בלבד",
      { fontSize: "30px", opacity: 0.5 },
      c
    );
    s.in(tag, 2.2, "fade");
    at += 8.6;
  });
  // formats
  s = E.seg(at, 8.4, { bg: "light" });
  c = s.safe({ gap: 30 });
  const hd = s.add(
    "div",
    "h2",
    "ואפשר *להוריד* הכול".replace(/\*(.*?)\*/, "<span class=hl>$1</span>"),
    null,
    c
  );
  s.in(hd, 0.2, "pop");
  const mx = S.formats[0][1];
  S.formats.slice(0, 5).forEach(([f, n], i) => {
    const row = s.add(
      "div",
      null,
      null,
      { display: "flex", alignItems: "center", gap: "24px", width: "100%" },
      c
    );
    s.add(
      "b",
      "ltr",
      f,
      { width: "170px", fontSize: "50px", color: "#0c3058" },
      row
    );
    const track = s.add(
      "div",
      null,
      null,
      {
        flex: 1,
        height: "58px",
        background: "#dbe7fb",
        borderRadius: "50rem",
        overflow: "hidden",
      },
      row
    );
    const fill = s.add(
      "div",
      null,
      null,
      {
        height: "100%",
        width: (n / mx) * 100 + "%",
        background: "#0068f5",
        borderRadius: "50rem",
        transformOrigin: "right center",
      },
      track
    );
    s.in(fill, 1 + i * 0.3, "grow", 0.9);
    const num = s.add(
      "b",
      "num",
      "0",
      { width: "110px", fontSize: "44px", color: "#0053c4" },
      row
    );
    s.count(num, 0, n, 1 + i * 0.3, 0.9);
  });
  const fl = s.add(
    "div",
    "p",
    "מספר המאגרים בכל פורמט",
    { fontSize: "36px", opacity: 0.6 },
    c
  );
  s.in(fl, 3, "fade");
  at += 8.1;
  // all in one
  s = E.seg(at, 6.2, { bg: "ink" });
  c = s.safe({ gap: 30 });
  const bar = s.add(
    "div",
    null,
    null,
    {
      display: "flex",
      width: "100%",
      height: "120px",
      borderRadius: "30px",
      overflow: "hidden",
      direction: "rtl",
    },
    c
  );
  const tot = S.datasets;
  [
    ["registry", "#ffc107"],
    ["timeseries", "#0dcaf0"],
    ["map", "#5ee08a"],
    ["misc", "#c3cfe7"],
    ["rankings", "#ff6b81"],
  ].forEach(([k, col], i) => {
    const seg = s.add(
      "div",
      null,
      null,
      {
        width: (K[k] / tot) * 100 + "%",
        background: col,
        transformOrigin: "right center",
      },
      bar
    );
    s.in(seg, 0.4 + i * 0.2, "grow", 0.8);
  });
  const t = s.add("div", "h2", null, null, c);
  s.words(t, "ביחד: *" + he(tot) + "* מאגרים", { at: 1.4, gap: 0.2 });
  const t2 = s.add("div", "h3", "כל אחד בעמוד שמתאים לו", null, c);
  s.in(t2, 2.6, "rise");
  at += 5.9;
  cta(E, at, 50 - at, "כל סוג — *עמוד משלו*", "ובעברית, מימין לשמאל");
}
