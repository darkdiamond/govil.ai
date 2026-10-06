import { sector, DURATION } from "./_sector.js";
export const duration = DURATION.S;
export default function (E) {
  sector(E, "env", {
    len: "S",
    hook: "מה *באוויר* שאנחנו נושמים?",
    hookSub: "",
    picks: [0, 3, 4],
    cta: "סביבה — *בשקיפות* מלאה",
    ctaSub: "מפעלים, אוויר וקרקעות",
    questions: [],
  });
}
