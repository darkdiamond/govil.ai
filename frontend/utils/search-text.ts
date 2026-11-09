// Search-text helpers shared by the header search and /datasets/.
//
// Two kinds of forgiveness:
//  - normalizeSearchText folds spellings that should match: final letters
//    (ך → כ), niqqud, quotes/geresh (צה"ל = צהל), hyphens/maqaf (תל-אביב =
//    תל אביב), case.
//  - queryVariants adds the query as it would read on the other keyboard
//    layout, for someone who typed Hebrew with the keyboard still on English
//    ("rfc" → "רכב"), or an English name with it on Hebrew ("עאכד" → "gtfs").

/** Standard Israeli keyboard layout (SI-1452): Latin key → Hebrew character. */
const EN_TO_HE: Record<string, string> = {
  q: "/",
  w: "'",
  e: "ק",
  r: "ר",
  t: "א",
  y: "ט",
  u: "ו",
  i: "ן",
  o: "ם",
  p: "פ",
  a: "ש",
  s: "ד",
  d: "ג",
  f: "כ",
  g: "ע",
  h: "י",
  j: "ח",
  k: "ל",
  l: "ך",
  ";": "ף",
  "'": ",",
  z: "ז",
  x: "ס",
  c: "ב",
  v: "ה",
  b: "נ",
  n: "מ",
  m: "צ",
  ",": "ת",
  ".": "ץ",
  "/": ".",
};

/** Reverse map, Hebrew letters only (punctuation stays as typed). */
const HE_TO_EN: Record<string, string> = Object.fromEntries(
  Object.entries(EN_TO_HE)
    .filter(([, he]) => /[א-ת]/.test(he))
    .map(([en, he]) => [he, en])
);

const HEBREW_LETTER = /[א-ת]/;
const LATIN_LETTER = /[a-z]/i;
const FINALS: Record<string, string> = {
  ך: "כ",
  ם: "מ",
  ן: "נ",
  ף: "פ",
  ץ: "צ",
};

const mapChars = (s: string, map: Record<string, string>) =>
  Array.from(s, (ch) => map[ch] ?? ch).join("");

/** What `s` reads as when typed with the keyboard on Hebrew instead of English. */
export function toHebrewLayout(s: string): string {
  return mapChars(s.toLowerCase(), EN_TO_HE);
}

/** What `s` reads as when typed with the keyboard on English instead of Hebrew. */
export function toLatinLayout(s: string): string {
  return mapChars(s, HE_TO_EN);
}

export function normalizeSearchText(s: string): string {
  return s
    .toLowerCase()
    .replace(/[֑-ׇ]/g, (ch) =>
      // keep maqaf (U+05BE) as a separator, drop niqqud/cantillation marks
      ch === "־" ? " " : ""
    )
    .replace(/[ךםןףץ]/g, (ch) => FINALS[ch] ?? ch)
    .replace(/["'`׳״“”‘’]/g, "")
    .replace(/[-_‐-―]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Searchable text of a dataset entry, normalized: what queryVariants() texts
 * are matched against (substring) on /datasets/ and in the header search. */
export function searchHaystack(e: {
  title: string;
  summary_he?: string | null;
  organization?: string | null;
  tags?: string[] | null;
}): string {
  return normalizeSearchText(
    `${e.title} ${e.summary_he ?? ""} ${(e.tags ?? []).join(" ")} ${e.organization ?? ""}`
  );
}

// A re-read shorter than this (spaces aside) is left out: two letters re-read
// as Hebrew are a common prefix ("ab" → "שנ", "co" → "במ") that matches nearly
// every dataset.
const MIN_CONVERTED_CHARS = 3;

export interface QueryVariant {
  /** Normalized text to match against normalizeSearchText() haystacks. */
  text: string;
  /** The variant as the user would read it (no folding), for display. */
  display: string;
  /** True when this variant is the query re-read on the other keyboard layout. */
  converted: boolean;
}

export function queryVariants(q: string): QueryVariant[] {
  const out: QueryVariant[] = [];
  const add = (display: string, converted: boolean) => {
    const text = normalizeSearchText(display);
    if (converted && text.replace(/ /g, "").length < MIN_CONVERTED_CHARS)
      return;
    if (text && !out.some((v) => v.text === text))
      out.push({ text, display: display.trim(), converted });
  };
  add(q, false);
  const hasHe = HEBREW_LETTER.test(q);
  const hasLat = LATIN_LETTER.test(q);
  if (hasLat && !hasHe) {
    const he = toHebrewLayout(q);
    if (HEBREW_LETTER.test(he)) add(he, true);
  } else if (hasHe && !hasLat) {
    const en = toLatinLayout(q);
    const norm = normalizeSearchText(en);
    if (/^[a-z0-9 ]+$/.test(norm) && LATIN_LETTER.test(norm)) add(en, true);
  }
  return out;
}
