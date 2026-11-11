// Topics of the /contact/ form. Each is also the option's value, which is what
// Formspree receives, and what a /contact/?topic= link must name.
export const CONTACT_TOPICS: readonly string[] = [
  "תיקון שגיאה / אי-דיוק בנתונים",
  "בקשת הוספת מאגר מ-data.gov.il",
  "נגישות האתר",
  "שאלה כללית",
  "שיתוף פעולה או תקשורת",
  "אחר",
];

/** The topic a ?topic= query preselects: an exact option, else none. */
export function topicFromQuery(q: unknown): string {
  const v = Array.isArray(q) ? q[0] : q;
  return typeof v === "string" && CONTACT_TOPICS.includes(v) ? v : "";
}
