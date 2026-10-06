import { sector, DURATION } from "./_sector.js";
export const duration = DURATION.L;
export default function (E) {
  sector(E, "bsheva", {
    len: "L",
    hook: "*עיר* אחת. כל כך הרבה נתונים",
    hookSub: "באר שבע — פתוחה לכולם",
    picks: [0, 2, 3],
    cta: "עיר — *בשקיפות* מלאה",
    ctaSub: "כל נתוני באר שבע — מוסברים בעברית",
    questions: [
      "כמה עצים יש ברחובות העיר?",
      "איפה נמצאים הדפיברילטורים?",
      "איך מתחלק תקציב העירייה?",
    ],
  });
}
