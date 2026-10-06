// Shared building blocks for the scenes (underscore = not rendered on its own).
import { rng } from "../engine/engine.js";

export const SECTORS = {
  transport: {
    org: "משרד התחבורה והבטיחות בדרכים",
    name: "תחבורה",
    icon: "bus",
    acc: "#ffc107",
    bg: "blue",
  },
  water: {
    org: "הרשות הממשלתית למים ולביוב",
    name: "מים",
    icon: "droplet",
    acc: "#0dcaf0",
    bg: "ink",
  },
  health: {
    org: "משרד הבריאות",
    name: "בריאות",
    icon: "heart",
    acc: "#ff6b81",
    bg: "ink",
  },
  env: {
    org: "המשרד להגנת הסביבה",
    name: "איכות הסביבה",
    icon: "leaf",
    acc: "#5ee08a",
    bg: "ink",
  },
  justice: {
    org: "משרד המשפטים",
    name: "משפט",
    icon: "scale",
    acc: "#ffc107",
    bg: "ink",
  },
  welfare: {
    org: "משרד הרווחה והביטחון החברתי",
    name: "רווחה",
    icon: "users",
    acc: "#ffa94d",
    bg: "blue",
  },
  agri: {
    org: "משרד החקלאות וביטחון המזון",
    name: "חקלאות",
    icon: "sprout",
    acc: "#b8e65c",
    bg: "ink",
  },
  bsheva: {
    org: "עיריית באר שבע",
    name: "באר שבע",
    icon: "building",
    acc: "#0dcaf0",
    bg: "blue",
  },
};
export const KIND_HE = {
  timeseries: "סדרת זמן",
  registry: "מאגר רשומות",
  map: "מפה",
  misc: "מידע נוסף",
  rankings: "דירוג",
};

export const hl = (t) => t.replace(/\*(.*?)\*/g, '<span class="hl">$1</span>');

// closing call-to-action card
export function cta(E, start, dur, line, sub, o = {}) {
  const s = E.seg(start, dur, { bg: o.bg || "blue", acc: o.acc });
  const c = s.safe({ gap: 50 });
  s.pulse(540, 760, "rgba(255,255,255,.5)", 0.2, { size: 420 });
  const h = s.add("div", "h1", null, null, c);
  s.words(h, line, { at: 0.2, gap: 0.16 });
  if (sub) {
    const p = s.add("div", "p", sub, null, c);
    s.in(p, 1.1, "rise");
  }
  const b = s.add("div", "btn ltr", "govil.ai", null, c);
  s.in(b, 1.6, "pop");
  s.confetti(26, { at: 1.6, y: 1000, seed: 11 });
  return s;
}

// illustrative motif per dataset kind, drawn inside `parent`; labelled as illustration by caller
export function motif(s, parent, kind, at, acc, seed = 5) {
  const r = rng(seed);
  const box = s.add(
    "div",
    null,
    null,
    { width: "880px", height: "420px", position: "relative" },
    parent
  );
  if (kind === "map") {
    for (let i = 0; i < 9; i++)
      s.add(
        "div",
        "abs",
        null,
        {
          left: 0,
          right: 0,
          top: i * 52 + "px",
          height: "2px",
          background: "rgba(255,255,255,.15)",
        },
        box
      );
    for (let i = 0; i < 12; i++)
      s.add(
        "div",
        "abs",
        null,
        {
          top: 0,
          bottom: 0,
          left: i * 80 + "px",
          width: "2px",
          background: "rgba(255,255,255,.15)",
        },
        box
      );
    for (let i = 0; i < 18; i++) {
      const p = s.add(
        "div",
        "abs",
        E_icon("pin", 64, acc),
        { left: 40 + r() * 760 + "px", top: 10 + r() * 300 + "px" },
        box
      );
      s.in(p, at + i * 0.12, "drop", 0.5, "back");
    }
  } else if (kind === "registry") {
    for (let i = 0; i < 7; i++) {
      const row = s.add(
        "div",
        null,
        null,
        { display: "flex", gap: "14px", marginBottom: "14px", height: "42px" },
        box
      );
      [180, 260, 140, 220].forEach((w, j) => {
        const cell = s.add(
          "div",
          null,
          null,
          {
            width: w * 0.85 + "px",
            borderRadius: "10px",
            background: j === 0 ? acc : "rgba(255,255,255,.22)",
            transformOrigin: "right center",
          },
          row
        );
        s.in(cell, at + i * 0.14 + j * 0.05, "grow", 0.5);
      });
    }
  } else {
    const pts = Array.from({ length: 14 }, (_, i) =>
      [
        i / 13,
        0.2 + 0.5 * (i / 13) + (r() - 0.5) * 0.35 + 0.12 * Math.sin(i / 1.4),
      ].map((v) => Math.max(0.05, Math.min(0.95, v)))
    );
    pts.forEach((p, i) => (p[0] = i / 13));
    s.line(box, pts, {
      w: 880,
      h: 420,
      color: acc,
      at,
      dur: 2.2,
      dots: false,
      sw: 12,
    });
  }
  return box;
}
import { icon as E_icon } from "../engine/engine.js";

// title + records card
export function datasetCard(E, s, parent, d, at, acc) {
  const card = s.add(
    "div",
    "card",
    null,
    { width: "100%", display: "flex", flexDirection: "column", gap: "10px" },
    parent
  );
  s.add(
    "div",
    null,
    d.title,
    { fontSize: d.title.length > 38 ? "44px" : "52px", fontWeight: 700 },
    card
  );
  const row = s.add(
    "div",
    null,
    null,
    { display: "flex", alignItems: "center", gap: "18px" },
    card
  );
  const n = s.add("b", "num", "0", { fontSize: "56px", color: "#0068f5" }, row);
  s.add("span", null, "שורות נתונים", { fontSize: "36px", opacity: 0.65 }, row);
  s.add(
    "span",
    null,
    KIND_HE[d.kind] || "",
    {
      marginInlineStart: "auto",
      fontSize: "30px",
      padding: "6px 22px",
      borderRadius: "50rem",
      background: "#e8f1ff",
      color: "#0053c4",
    },
    row
  );
  s.in(card, at, "slideR", 0.6);
  s.count(n, 0, d.records, at + 0.3, 1.4);
  return card;
}

export function pickSector(E, key) {
  const def = SECTORS[key];
  const st = E.stats.sector_top[def.org];
  return {
    ...def,
    datasets: st.datasets,
    records: st.records,
    kinds: st.kinds,
    top: st.top,
  };
}
