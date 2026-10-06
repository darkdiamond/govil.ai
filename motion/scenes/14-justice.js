import { sector, DURATION } from "./_sector.js";
export const duration = DURATION.L;
export default function (E) {
  sector(E, "justice", {
    len: "L",
    hook: "מה רשום *על* הנכס שלכם?",
    hookSub: "המשפט הפתוח לציבור",
    picks: [1, 2, 0],
    cta: "צדק — *גלוי* לכולם",
    ctaSub: "כל נתוני המשפט — מוסברים בעברית",
    questions: [
      "כיצד מתחלקת הבעלות בנכסים?",
      "כמה בקשות לסיוע משפטי הוגשו?",
      "מה הכנסות וגבייה של משרד המשפטים?",
    ],
  });
}
