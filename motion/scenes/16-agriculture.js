import { sector, DURATION } from "./_sector.js";
export const duration = DURATION.S;
export default function (E) {
  sector(E, "agri", {
    len: "S",
    hook: "מה יש *בצלחת* שלכם?",
    hookSub: "",
    picks: [0, 1, 2],
    cta: "מהשדה — *אליכם*",
    ctaSub: "חקלאות וביטחון מזון בנתונים",
    questions: [],
  });
}
