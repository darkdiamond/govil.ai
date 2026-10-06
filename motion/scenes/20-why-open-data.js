// 20 · למה מידע פתוח (L, 50s) — kinetic-type manifesto
import { cta } from "./_kit.js";
export const duration = 50;
export default function (E) {
  const { stats: S, he, mil } = E;
  const lines = [
    { bg: "blue", big: "נתונים *ציבוריים*", sub: "כסף ציבורי. ידע ציבורי." },
    { bg: "ink", big: "הם *שלכם*", sub: "כל אזרח, כל סטודנט, כל עיתונאי" },
    { bg: "light", big: "אבל קובץ של 5 מיליון שורות הוא *לא ידע*", sub: "" },
    { bg: "ink", big: "ידע זה *הבנה*", sub: "גרף. סיכום. הקשר." },
    {
      bg: "blue",
      big: `${mil(S.records)} שורות הפכו ל־${he(S.datasets)} *עמודים*`,
      sub: "שאפשר לקרוא בטלפון",
    },
    { bg: "light", big: "בעברית. *מימין לשמאל*.", sub: "כמו שצריך" },
    { bg: "ink", big: "פתוח *לכולם*", sub: "בלי הרשמה. בלי תואר." },
    { bg: "blue", big: "יש לכם *זכות* לדעת", sub: "עכשיו גם אפשרות" },
  ];
  const d = 5.0;
  let at = 0;
  lines.forEach((ln, i) => {
    const s = E.seg(at, d + 0.3, {
      bg: ln.bg,
      acc: ln.bg === "ink" ? "#ffc107" : undefined,
    });
    const c = s.safe({ gap: 44 });
    const num = s.add(
      "div",
      null,
      String(i + 1).padStart(2, "0"),
      {
        position: "absolute",
        top: "200px",
        left: "70px",
        fontSize: "90px",
        fontWeight: 800,
        opacity: 0.25,
      },
      s.el
    );
    s.in(num, 0, "fade");
    const h = s.add(
      "div",
      "h1",
      null,
      { fontSize: ln.big.length > 30 ? "104px" : "128px" },
      c
    );
    s.words(h, ln.big, { at: 0.2, gap: 0.17 });
    if (ln.sub) {
      const p = s.add("div", "p", ln.sub, null, c);
      s.in(p, 1.5 + ln.big.split(" ").length * 0.17, "rise");
    }
    const bar = s.add(
      "div",
      null,
      null,
      {
        width: "240px",
        height: "12px",
        borderRadius: "12px",
        background: "var(--acc)",
        transformOrigin: "right center",
      },
      c
    );
    s.in(bar, 0.9 + ln.big.split(" ").length * 0.17, "grow", 0.6);
    at += d;
  });
  cta(E, at - 0.1, 50 - at + 0.1, "הנתונים *שלכם*", "govil.ai — פתוח לכולם");
}
