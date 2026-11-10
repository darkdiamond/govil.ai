// Hebrew points and cantillation marks (the combining marks in U+0591-U+05C7;
// maqaf, paseq and sof pasuq there are punctuation and stay separators).
const HEBREW_MARK = /(?=\p{M})[֑-ׇ]/gu;
// A quote, geresh or gershayim between two Hebrew letters (צה"ל, ג'ורג')
// is part of the word, not a separator.
const INNER_GERESH = /(?<=[א-ת])["'`׳״“”‘’](?=[א-ת])/g;

// Turn free user input into a safe PostgreSQL tsquery: every word
// becomes a prefix match (tok:*), multiple words AND together. Any
// non-letter/digit char is stripped first — raw tsquery metacharacters
// (& | ! ( ) : * ' ") make CKAN return an Invalid-query error.
export function buildTsQuery(raw: string): string | null {
  const tokens = raw
    .normalize("NFD")
    .replace(HEBREW_MARK, "")
    .normalize("NFC")
    .replace(INNER_GERESH, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .split(" ")
    .filter(Boolean)
    .slice(0, 6);
  if (!tokens.length) return null;
  return tokens.map((t) => `${t}:*`).join(" & ");
}
