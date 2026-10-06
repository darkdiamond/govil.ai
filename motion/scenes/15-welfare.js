import { sector, DURATION } from "./_sector.js";
export const duration = DURATION.S;
export default function (E) {
  sector(E, "welfare", {
    len: "S",
    hook: "מי *עומד* מאחורי שירותי הרווחה?",
    hookSub: "",
    picks: [0, 1, 2],
    cta: "רווחה — *בשקיפות* מלאה",
    ctaSub: "מסגרות, עובדים ושירותים",
    questions: [],
  });
}
