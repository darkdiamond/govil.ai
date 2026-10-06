import { sector, DURATION } from "./_sector.js";
export const duration = DURATION.L;
export default function (E) {
  sector(E, "health", {
    len: "L",
    hook: "*כמה* תינוקות נולדים בישראל?",
    hookSub: "התשובה בנתונים",
    picks: [1, 0, 2],
    cta: "בריאות — *מבוססת* נתונים",
    ctaSub: "כל נתוני הבריאות — מוסברים בעברית",
    questions: [
      "איך נראים מדדי האיכות של טיפות חלב?",
      "מה ידוע על מחלות נדירות?",
      "איך בודקים רישיון של רופא?",
    ],
  });
}
