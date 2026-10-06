import { sector, DURATION } from "./_sector.js";
export const duration = DURATION.S;
export default function (E) {
  sector(E, "water", {
    len: "S",
    hook: "מה קורה *מתחת* לרגליים שלנו?",
    hookSub: "",
    picks: [0, 2, 3],
    cta: "מים — *בשקיפות* מלאה",
    ctaSub: "מפלסים, מעיינות ואיכות מים",
    questions: [],
  });
}
