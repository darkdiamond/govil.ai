// Hebrew points and cantillation marks (the combining marks in U+0591-U+05C7;
// maqaf, paseq and sof pasuq there are punctuation and stay separators).
const HEBREW_MARK = /(?=\p{M})[֑-ׇ]/gu;
// A quote, geresh or gershayim between two Hebrew letters (צה"ל, ג'ורג').
// The datastore index splits the word there, so its parts are searched as a
// phrase (צה <-> ל:*), not as separate terms.
const INNER_GERESH = /(?<=[א-ת])["'`׳״“”‘’](?=[א-ת])/g;
// Stands for an inner geresh until the word is split into its parts. Removed
// from the input first, so only INNER_GERESH produces it.
const JOIN = "\u0000";

// Turn free user input into a safe PostgreSQL tsquery: every word
// becomes a prefix match (tok:*), multiple words AND together. Any
// non-letter/digit char is stripped first — raw tsquery metacharacters
// (& | ! ( ) : * ' ") make CKAN return an Invalid-query error. The only
// operators in the output (&, <->, :*) are written here.
export function buildTsQuery(raw: string): string | null {
  const tokens = raw
    .replaceAll(JOIN, " ")
    .normalize("NFD")
    .replace(HEBREW_MARK, "")
    .normalize("NFC")
    .replace(INNER_GERESH, JOIN)
    .replace(/[^\p{L}\p{N}\u0000]+/gu, " ")
    .split(" ")
    .filter(Boolean)
    .slice(0, 6);
  if (!tokens.length) return null;
  return tokens.map((t) => `${t.split(JOIN).join(" <-> ")}:*`).join(" & ");
}
