import { sector, DURATION } from "./_sector.js";
export const duration = DURATION.L;
export default function (E) {
  sector(E, "transport", {
    len: "L",
    hook: "*האוטובוס* מאחר? יש על זה נתונים",
    hookSub: "ויש עוד המון בתחבורה",
    picks: [0, 1, 3],
    cta: "לכו *רחוק* עם הנתונים",
    ctaSub: "כל נתוני התחבורה — מוסברים בעברית",
    questions: [
      "כמה נסיעות אוטובוס מתוכננות, וכמה בפועל מבוצעות?",
      "כמה כלי רכב ירדו מהכביש לתמיד?",
      "אילו מערכות בטיחות יש ברכב?",
    ],
  });
}
