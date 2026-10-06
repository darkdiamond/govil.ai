// 07 · מאגרים מחוברים (S, 18s) — related-dataset network
import { cta } from "./_kit.js";
export const duration = 18;
export default function (E) {
  const { stats: S, he } = E;
  let s = E.seg(0, 3.4, { bg: "blue" });
  let c = s.safe();
  const h = s.add("div", "h1", null, null, c);
  s.words(h, "מאגר אחד לא מספר את *כל* הסיפור", { at: 0.2, gap: 0.14 });

  s = E.seg(3.1, 9.2, { bg: "ink", acc: "#0dcaf0" });
  const W = 940,
    H = 1000;
  const box = s.add(
    "div",
    "abs",
    null,
    { left: "70px", top: "330px", width: W + "px", height: H + "px" },
    s.el
  );
  const cx = W / 2,
    cy = H / 2,
    r = E.rng(14);
  const names = [
    "זמני הגעה לתחנה",
    "תכנון מול ביצוע",
    "רישוי אוטובוסים",
    "תחנות",
    "כלי רכב",
    "תיקופי מסלקה",
    "בטיחות",
    "ביטולי רכב",
  ];
  const nodes = [];
  for (let i = 0; i < 22; i++) {
    const ring = i < 8 ? 1 : 2,
      a = (i / (ring === 1 ? 8 : 14)) * Math.PI * 2 + r();
    const rad = ring === 1 ? 300 : 420 + r() * 40;
    nodes.push([
      cx + Math.cos(a) * rad * 1.0,
      cy + Math.sin(a) * rad * 0.95,
      ring,
      i,
    ]);
  }
  const svg = s.add(
    "div",
    "abs",
    `<svg width="${W}" height="${H}" style="position:absolute;inset:0">${nodes.map(([x, y, ring]) => `<line class="e" x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" pathLength="1" stroke="${ring === 1 ? "#0dcaf0" : "#3d7bd4"}" stroke-width="${ring === 1 ? 5 : 3}" stroke-dasharray="1" stroke-dashoffset="1"/>`).join("")}</svg>`,
    { inset: 0 },
    box
  );
  svg
    .querySelectorAll(".e")
    .forEach((l, i) =>
      s.anim(
        l,
        [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }],
        1.2 + i * 0.12,
        0.7,
        "out"
      )
    );
  nodes.forEach(([x, y, ring, i]) => {
    const d = ring === 1 ? 54 : 30;
    const n = s.add(
      "div",
      "abs",
      null,
      {
        left: x - d / 2 + "px",
        top: y - d / 2 + "px",
        width: d + "px",
        height: d + "px",
        borderRadius: "50%",
        background: ring === 1 ? "#0dcaf0" : "#7fb0ff",
      },
      box
    );
    s.in(n, 1.5 + i * 0.12, "pop", 0.4);
  });
  const mid = s.add(
    "div",
    "abs",
    null,
    {
      left: cx - 70 + "px",
      top: cy - 70 + "px",
      width: "140px",
      height: "140px",
      borderRadius: "50%",
      background: "#ffc107",
      display: "grid",
      placeItems: "center",
    },
    box
  );
  mid.innerHTML = E.icon("db", 80, "#0c3058", 2.2);
  s.in(mid, 0.2, "pop");
  s.pulse(70 + cx, 330 + cy, "#ffc107", 0.5, { size: 200, n: 2 });
  s.drift(box, [{ rotate: "-4deg" }, { rotate: "4deg" }]);
  const cap = s.add(
    "div",
    "h3",
    "כל עמוד מצביע על מאגרים *קרובים* אליו".replace(
      /\*(.*?)\*/,
      "<span class=hl>$1</span>"
    ),
    {
      position: "absolute",
      left: "70px",
      right: "70px",
      top: "1400px",
      fontSize: "52px",
    },
    s.el
  );
  s.in(cap, 4.5, "rise");

  s = E.seg(12, 3.4, { bg: "light" });
  c = s.safe({ gap: 30 });
  const n = s.add("div", "big hl", "0", { fontSize: "220px" }, c);
  s.in(n, 0.2, "pop");
  s.count(n, 0, S.related_links, 0.3, 1.8);
  const l = s.add("div", "h2", "קישורים בין מאגרים", null, c);
  s.in(l, 0.6, "rise");
  const l2 = s.add("div", "p", "כדי שלא תפספסו את התמונה המלאה", null, c);
  s.in(l2, 1.6, "fade");
  cta(E, 15.1, 2.9, "עוד נתון. עוד *נתון*.", "ועוד תובנה");
}
