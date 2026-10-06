// Deterministic, seekable motion engine. Every animation is a paused Web Animation
// (or a registered tick) driven by E.seek(t) — so any frame renders identically.
export const EASE = {
  out: "cubic-bezier(.16,1,.3,1)",
  inout: "cubic-bezier(.65,0,.35,1)",
  back: "cubic-bezier(.34,1.56,.64,1)",
  lin: "linear",
  in: "cubic-bezier(.7,0,.84,0)",
  soft: "cubic-bezier(.33,1,.68,1)",
};
const ICONS = {
  droplet:
    "M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z",
  heart:
    "M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z",
  leaf: "M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10ZM2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12",
  bus: "M8 6v6M15 6v6M2 12h19.6M18 18h3s.5-1.7.8-2.8c.1-.4.2-.8.2-1.2 0-.4-.1-.8-.2-1.2l-1.4-5C20.1 6.8 19.1 6 18 6H4a2 2 0 0 0-2 2v10h3M9 18h5M5 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0M16 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0",
  scale:
    "M16 16l3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1ZM2 16l3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1ZM7 21h10M12 3v18M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2",
  sprout:
    "M7 20h10M10 20c5.5-2.5.8-6.4 3-10M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8zM14.1 6a7 7 0 0 0-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z",
  users:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  clock: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M12 6v6l4 2",
  link: "M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71",
  chart: "M12 20V10M18 20V4M6 20v-4",
  trend: "M22 7l-8.5 8.5-5-5L2 17M16 7h6v6",
  zap: "M13 2 3 14h9l-1 8 10-12h-9l1-8z",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8",
  globe:
    "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z",
  wind: "M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2M9.6 4.6A2 2 0 1 1 11 8H2M12.6 19.4A2 2 0 1 0 14 16H2",
  car: "M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2M9 17h6M7 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0M17 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0",
  home: "m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM9 22V12h6v10",
  pin: "M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0M12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
  search: "M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16M21 21l-4.3-4.3",
  db: "M12 3c4.97 0 9 1.34 9 3s-4.03 3-9 3-9-1.34-9-3 4.03-3 9-3M3 6v6c0 1.66 4.03 3 9 3s9-1.34 9-3V6M3 12v6c0 1.66 4.03 3 9 3s9-1.34 9-3v-6",
  building:
    "M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18zM6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2M10 6h4M10 10h4M10 14h4M10 18h4",
  check: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M9 12l2 2 4-4",
  tree: "M12 22v-7M9 15h6l-3-5 4 0-4-6-4 6 4 0z",
  moon: "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  shield:
    "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z",
  baby: "M9 12h.01M15 12h.01M10 16c.5.3 1.2.5 2 .5s1.5-.2 2-.5M19 6.3a9 9 0 0 1 1.8 3.9 2 2 0 0 1 0 3.6 9 9 0 0 1-17.6 0 2 2 0 0 1 0-3.6A9 9 0 0 1 12 3c2 0 3.5 1.1 3.5 2.5s-.9 2.5-2 2.5c-.8 0-1.5-.4-1.5-1",
  pill: "m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7ZM8.5 8.5l7 7",
  coin: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M14.8 9A2 2 0 0 0 13 8h-2a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4h-2a2 2 0 0 1-1.8-1M12 6v2M12 16v2",
};
export function icon(name, size = 80, color = "currentColor", sw = 2) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round"><path d="${ICONS[name]}"/></svg>`;
}
export function rng(seed = 1) {
  // mulberry32 — deterministic "random"
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export const he = (n) => Math.round(n).toLocaleString("he-IL");
export function mil(n) {
  // 80062244 -> "80 מיליון"
  if (n >= 1e6)
    return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, "")} מיליון`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} אלף`;
  return String(n);
}

const KF = {
  rise: [
    { opacity: 0, translate: "0 70px" },
    { opacity: 1, translate: "0 0" },
  ],
  drop: [
    { opacity: 0, translate: "0 -70px" },
    { opacity: 1, translate: "0 0" },
  ],
  fade: [{ opacity: 0 }, { opacity: 1 }],
  pop: [
    { opacity: 0, scale: ".4" },
    { opacity: 1, scale: "1" },
  ],
  zoom: [
    { opacity: 0, scale: "1.5" },
    { opacity: 1, scale: "1" },
  ],
  slideR: [
    { opacity: 0, translate: "220px 0" },
    { opacity: 1, translate: "0 0" },
  ],
  slideL: [
    { opacity: 0, translate: "-220px 0" },
    { opacity: 1, translate: "0 0" },
  ],
  wipe: [{ clipPath: "inset(0 0 0 100%)" }, { clipPath: "inset(0 0 0 0)" }],
  wipeUp: [{ clipPath: "inset(100% 0 0 0)" }, { clipPath: "inset(0 0 0 0)" }],
  blur: [
    { opacity: 0, filter: "blur(30px)", scale: "1.1" },
    { opacity: 1, filter: "blur(0)", scale: "1" },
  ],
  flip: [
    { opacity: 0, transform: "perspective(900px) rotateX(80deg)" },
    { opacity: 1, transform: "perspective(900px) rotateX(0)" },
  ],
  grow: [
    { scale: "0 1", opacity: 1 },
    { scale: "1 1", opacity: 1 },
  ],
  growY: [
    { scale: "1 0", opacity: 1 },
    { scale: "1 1", opacity: 1 },
  ],
};
const KFOUT = {
  fade: [{ opacity: 1 }, { opacity: 0 }],
  rise: [
    { opacity: 1, translate: "0 0" },
    { opacity: 0, translate: "0 -70px" },
  ],
  drop: [
    { opacity: 1, translate: "0 0" },
    { opacity: 0, translate: "0 70px" },
  ],
  pop: [
    { opacity: 1, scale: "1" },
    { opacity: 0, scale: ".6" },
  ],
  zoom: [
    { opacity: 1, scale: "1" },
    { opacity: 0, scale: "1.6" },
  ],
  slideL: [
    { opacity: 1, translate: "0 0" },
    { opacity: 0, translate: "-260px 0" },
  ],
  slideR: [
    { opacity: 1, translate: "0 0" },
    { opacity: 0, translate: "260px 0" },
  ],
};
const ENTER_EASE = { pop: "back", flip: "out", grow: "out", growY: "out" };

export function createEngine(stage, stats) {
  const anims = [],
    ticks = [];
  const events = [];
  const E = {
    events,
    ev: (t, k, x = {}) => events.push({ t: +t.toFixed(3), k, ...x }),
    stage,
    stats,
    W: 1080,
    H: 1920,
    EASE,
    icon,
    rng,
    he,
    mil,
    KF,
  };

  function make(tag, cls, html, parent, style) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    if (style) Object.assign(e.style, style);
    if (parent) parent.appendChild(e);
    return e;
  }
  E.make = make;
  E.anim = (el, kf, at, dur, ease = "out", fill = "both") => {
    const a = el.animate(kf, {
      delay: Math.max(0, at) * 1000,
      duration: Math.max(1, dur * 1000),
      fill,
      easing: EASE[ease] || ease,
    });
    a.pause();
    anims.push(a);
    return a;
  };
  E.tick = (fn) => ticks.push(fn);
  E.seek = (t) => {
    anims.forEach((a) => {
      a.currentTime = t * 1000;
    });
    ticks.forEach((f) => f(t));
  };

  // persistent chrome (progress bar + brand chip) is added in finish() so it sits on top
  E.finish = (total) => {
    const ch = make("div", "chrome", null, stage);
    const prog = make("div", "prog", "<b></b>", ch);
    E.anim(
      prog.firstChild,
      [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }],
      0,
      total,
      "lin"
    );
    make("div", "brand", "<i></i>govil.ai", ch);
  };

  class Seg {
    constructor(start, dur, o = {}) {
      this.start = start;
      this.dur = dur;
      this.o = o;
      this.el = make("div", `seg ${o.bg || "blue"}`, null, stage);
      if (o.acc) this.el.style.setProperty("--acc", o.acc);
      const fin = o.cut ? 0.001 : (o.fadeIn ?? 0.3),
        fout = o.cut ? 0.001 : (o.fadeOut ?? 0.3);
      if (!o.cut) E.ev(start, "seg");
      E.anim(this.el, [{ opacity: 0 }, { opacity: 1 }], start, fin, "lin");
      if (start + dur < 9999)
        E.anim(
          this.el,
          [{ opacity: 1 }, { opacity: 0 }],
          start + dur - fout,
          fout,
          "lin",
          "forwards"
        );
    }
    add(tag, cls, html, style, parent) {
      return make(tag, cls, html, parent || this.el, style);
    }
    safe(style) {
      return make("div", "safe", null, this.el, style);
    }
    in(el, at = 0, kind = "rise", dur = 0.6, ease, quiet = false) {
      if (!quiet) E.ev(this.start + at, kind);
      return E.anim(
        el,
        KF[kind],
        this.start + at,
        dur,
        ease || ENTER_EASE[kind] || "out"
      );
    }
    out(el, at, kind = "fade", dur = 0.35) {
      return E.anim(el, KFOUT[kind], this.start + at, dur, "inout", "forwards");
    }
    anim(el, kf, at, dur, ease = "out", fill = "both") {
      return E.anim(el, kf, this.start + at, dur, ease, fill);
    }
    // continuous drift across the whole segment (use on wrappers that have no entrance on the same property)
    drift(el, kf, at = 0, dur = this.dur, ease = "inout") {
      return E.anim(el, kf, this.start + at, dur, ease);
    }
    // kinetic text: words rise in one by one. *word* toggles highlight.
    words(parent, text, o = {}) {
      const { at = 0, gap = 0.1, kind = "rise", dur = 0.55, cls = "" } = o;
      let hl = false,
        i = 0;
      const spans = [];
      text.split(" ").forEach((tok) => {
        const n = (tok.match(/\*/g) || []).length;
        const clean = tok.replace(/\*/g, "");
        const startHl = hl || tok.startsWith("*");
        if (n % 2 === 1) hl = !hl;
        const s = make(
          "span",
          `w${startHl ? " hl" : ""} ${cls}`,
          clean + " ",
          parent
        );
        this.in(s, at + i * gap, kind, dur, undefined, true);
        E.ev(this.start + at + i * gap, "word");
        spans.push(s);
        i++;
      });
      return spans;
    }
    // number counter
    count(el, from, to, at, dur, o = {}) {
      const {
        fmt = he,
        pre = "",
        suf = "",
        ease = (x) => 1 - Math.pow(1 - x, 3),
      } = o;
      const a = this.start + at;
      E.ev(a, "count", { dur });
      const f = (t) => {
        const k = Math.min(1, Math.max(0, (t - a) / dur));
        el.textContent = pre + fmt(from + (to - from) * ease(k)) + suf;
      };
      f(0);
      E.tick(f);
    }
    // seeded dots/icons flying around; returns elements
    confetti(n, o = {}) {
      const {
        at = 0,
        colors = ["#ffc107", "#0dcaf0", "#fff", "#0068f5"],
        seed = 7,
        size = [10, 26],
        dur = 2.2,
        spread = 900,
      } = o;
      E.ev(this.start + at, "confetti");
      const r = rng(seed);
      const out = [];
      for (let i = 0; i < n; i++) {
        const s = size[0] + r() * (size[1] - size[0]);
        const d = make("div", "abs", null, this.el, {
          left: "540px",
          top: (o.y ?? 900) + "px",
          width: s + "px",
          height: s + "px",
          borderRadius: r() > 0.5 ? "50%" : "4px",
          background: colors[i % colors.length],
        });
        const ang = r() * Math.PI * 2,
          dist = spread * (0.35 + r() * 0.65);
        const dx = Math.cos(ang) * dist,
          dy = Math.sin(ang) * dist * 0.8;
        this.anim(
          d,
          [
            { translate: "0 0", opacity: 1, rotate: "0deg" },
            {
              translate: `${dx}px ${dy}px`,
              opacity: 0,
              rotate: `${r() * 540}deg`,
            },
          ],
          at + r() * 0.15,
          dur * (0.7 + r() * 0.5),
          "out"
        );
        out.push(d);
      }
      return out;
    }
    // expanding ring pulses
    pulse(x, y, color, at, o = {}) {
      const { n = 3, size = 300, dur = 1.6, gap = 0.45, w = 8 } = o;
      const out = [];
      for (let i = 0; i < n; i++) E.ev(this.start + at + i * gap, "ping");
      for (let i = 0; i < n; i++) {
        const r = make("div", "abs", null, this.el, {
          left: x - size / 2 + "px",
          top: y - size / 2 + "px",
          width: size + "px",
          height: size + "px",
          borderRadius: "50%",
          border: `${w}px solid ${color}`,
          opacity: 0,
        });
        this.anim(
          r,
          [
            { opacity: 0.9, scale: ".2" },
            { opacity: 0, scale: "2.6" },
          ],
          at + i * gap,
          dur,
          "out"
        );
        out.push(r);
      }
      return out;
    }
    // line chart: points [[x,y]...] in a w×h box. Returns wrapper.
    line(parent, pts, o = {}) {
      const {
        w = 900,
        h = 520,
        color = "#ffc107",
        at = 0,
        dur = 2,
        sw = 12,
        area = true,
        dots = true,
      } = o;
      const d = pts
        .map((p, i) => `${i ? "L" : "M"}${p[0] * w},${(1 - p[1]) * h}`)
        .join(" ");
      const wrap = make(
        "div",
        null,
        `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        ${area ? `<path class="ar" d="${d} L${w},${h} L0,${h} Z" fill="${color}" opacity=".18"/>` : ""}
        <path class="ln" d="${d}" pathLength="1" fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="1" stroke-dashoffset="1"/>
        ${dots ? pts.map((p, i) => `<circle class="dt" cx="${p[0] * w}" cy="${(1 - p[1]) * h}" r="${sw * 0.9}" fill="#fff" stroke="${color}" stroke-width="${sw * 0.5}"/>`).join("") : ""}</svg>`,
        parent
      );
      E.ev(this.start + at, "draw", { dur });
      const ln = wrap.querySelector(".ln");
      this.anim(
        ln,
        [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }],
        at,
        dur,
        "inout"
      );
      const ar = wrap.querySelector(".ar");
      if (ar)
        this.anim(
          ar,
          [{ opacity: 0 }, { opacity: 0.18 }],
          at + dur * 0.5,
          dur * 0.6,
          "lin"
        );
      wrap.querySelectorAll(".dt").forEach((c, i) =>
        this.anim(
          c,
          [
            { opacity: 0, scale: "0" },
            { opacity: 1, scale: "1" },
          ],
          at + dur * (i / (pts.length - 1)) * 0.95,
          0.35,
          "back"
        )
      );
      return wrap;
    }
    // vertical bar chart. vals 0..1
    bars(parent, vals, o = {}) {
      const {
        w = 900,
        h = 520,
        color = "#ffc107",
        at = 0,
        gap = 0.12,
        stagger = 0.08,
        dur = 0.8,
        colors,
        radius = 14,
      } = o;
      const bw = w / vals.length;
      const wrap = make("div", "abs", null, parent, {
        position: "relative",
        width: w + "px",
        height: h + "px",
        display: "flex",
        alignItems: "flex-end",
        gap: bw * gap + "px",
      });
      vals.forEach((v, i) => {
        const b = make("div", null, null, wrap, {
          flex: 1,
          height: v * h + "px",
          background: (colors && colors[i]) || color,
          borderRadius: `${radius}px ${radius}px 0 0`,
          transformOrigin: "bottom center",
        });
        this.in(b, at + i * stagger, "growY", dur);
      });
      return wrap;
    }
    // grid of dots appearing in a wave
    dotGrid(parent, cols, count, o = {}) {
      const {
        size = 22,
        gap = 11,
        at = 0,
        dur = 2.4,
        color = "#fff",
        alt = "#ffc107",
        altEvery = 0,
        seed = 3,
      } = o;
      const r = rng(seed);
      const wrap = make("div", null, null, parent, {
        display: "grid",
        gridTemplateColumns: `repeat(${cols},${size}px)`,
        gap: gap + "px",
        direction: "rtl",
      });
      for (let i = 0; i < count; i++) {
        const isAlt = altEvery && r() < 1 / altEvery;
        const d = make("div", null, null, wrap, {
          width: size + "px",
          height: size + "px",
          borderRadius: "50%",
          background: isAlt ? alt : color,
        });
        const row = Math.floor(i / cols),
          col = i % cols;
        this.anim(
          d,
          [
            { opacity: 0, scale: "0" },
            { opacity: isAlt ? 1 : 0.85, scale: "1" },
          ],
          at + (i / count) * dur + (col % 3) * 0.01,
          0.35,
          "back"
        );
      }
      return wrap;
    }
    // typewriter (for search boxes) — reveals characters via tick
    type(el, text, at, cps = 12, caret = true) {
      const a = this.start + at;
      E.ev(a, "type", { n: text.length, cps });
      const f = (t) => {
        const n = Math.max(0, Math.min(text.length, Math.floor((t - a) * cps)));
        el.textContent =
          text.slice(0, n) +
          (caret && ((t * 2) | 0) % 2 === 0 && n < text.length + 40 ? "|" : "");
      };
      f(0);
      E.tick(f);
    }
  }
  E.seg = (start, dur, o) => new Seg(start, dur, o);
  return E;
}
